"""
core/robot_agent.py
====================
The decision-making loop that would run on each robot's onboard computer.
This class is transport-agnostic: it doesn't know if `send()` goes out over
a real UDP socket (live demo) or is just a function call into a simulator
(fast_sim). That separation is what lets us prove the algorithm's timing
benefit quickly while also having an honest, real peer-to-peer demo.

State machine per robot:
    IDLE -> BIDDING -> EN_ROUTE_TO_PICKUP -> AT_PICKUP -> EN_ROUTE_TO_DROPOFF
         -> AT_DROPOFF -> IDLE  (loop)
    any state -> BLOCKED -> (replan) -> resumes
    battery low -> EN_ROUTE_TO_CHARGE -> CHARGING -> IDLE
"""
from __future__ import annotations
import time
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from collections import deque
from core import config
from core.planner import (WarehouseMap, astar, ReservationBook, PeerIntent,
                           resolve_conflict, apply_aging, Cell, manhattan,
                           FREE, PICKUP, DROPOFF, CHARGE, l2_safety_shield,
                           build_congestion_heatmap)
from core.pibt import PIBTAgentState, run_pibt_step
from core.deadlock import local_deadlock_victim
from core.dstar_lite import DStarLite
from core.auction import hungarian_batch_assign
from core.perception import EdgePerceptionModel

PLAN_HORIZON = 6           # how many future steps a robot broadcasts as "intent"
LOW_BATTERY = 20.0
FULL_BATTERY = 100.0
BATTERY_DRAIN_PER_MOVE = 0.35
BATTERY_CHARGE_PER_TICK = 8.0
STARVATION_WAIT_LIMIT = 10
AVOID_WINDOW = 15          # ticks a just-contested cell is treated as a
                            # soft no-go by THIS robot's own planner after a
                            # starvation-triggered replan -- without this, a
                            # fresh astar search over an unchanged map simply
                            # re-discovers the identical (still-blocked)
                            # shortest path, producing a livelock where the
                            # robot "replans" forever without ever actually
                            # trying a different route
PIBT_LOCAL_RADIUS = 4      # L4 only considers peers within this many cells (~2 ticks
                            # of travel each way) -- local, not fleet-wide, coordination
PIBT_STALL_TICKS = 2       # ticks PIBT may hold us before the L2 shield arbitrates an empty cell
BASELINE_WAIT_TIMEOUT = 8  # stop-and-wait baseline: ticks blocked before trying a detour
AUCTION_WINDOW_TICKS = 3   # ticks a task stays open for bids before any robot
                            # is allowed to declare a winner -- gives every
                            # peer's bid broadcast time to actually arrive
                            # over the network before settlement happens


@dataclass
class Task:
    task_id: str
    pickup: Cell
    dropoff: Cell
    created_t: int = 0


@dataclass
class RobotAgent:
    robot_id: str
    pos: Cell
    wmap: WarehouseMap
    send: Callable[[dict], None]           # broadcast a message to peers
    priority_base: int = 10
    battery: float = 100.0
    speed_ticks_per_cell: int = 1           # kept =1 for grid-tick simplicity

    cooperative: bool = True   # False => naive "stop-and-wait" baseline behaviour:
                                 # blind static planning (ignores peers' future
                                 # intent) + reactive-only halting with NO
                                 # replanning/rerouting around a stuck peer.
                                 # Used to measure the benefit of the
                                 # decentralized cooperative approach.
    state: str = "IDLE"
    path: List[Cell] = field(default_factory=list)
    current_task: Optional[Task] = None
    known_tasks: Dict[str, Task] = field(default_factory=dict)
    open_bids: Dict[str, Dict[str, float]] = field(default_factory=dict)  # task_id -> {robot_id: cost}
    queued_tasks: List[Task] = field(default_factory=list)
    book: ReservationBook = field(init=False)
    wait_ticks: int = 0
    t: int = 0                              # local logical clock
    completed_tasks: int = 0
    total_wait_ticks: int = 0
    _interrupted_state: Optional[str] = field(default=None, repr=False)
    avoid_until: Dict[Cell, int] = field(default_factory=dict, repr=False)
    nudged: bool = False
    display_status: str = ""
    dstar_router: Optional[DStarLite] = field(default=None, repr=False)
    perception: Optional[EdgePerceptionModel] = field(default=None, repr=False)
    # Physical obstacles the onboard camera can see (injected by the simulator /
    # real sensor driver). The robot's map does NOT know about them until L1 detects them.
    sensor_truth: Optional[set] = field(default=None, repr=False)
    last_rank: Optional[tuple] = field(default=None, repr=False)  # rank in our last intent broadcast
    goal_since_t: int = 0                    # tick our current (PIBT) goal was set
    _rank_goal: Optional[Cell] = field(default=None, repr=False)

    def __post_init__(self):
        self.book = ReservationBook(self.robot_id)
        self.home = self._pick_home(self.pos)
        self.start_pos = self.pos
        self.perception = EdgePerceptionModel(rng_seed=abs(hash(self.robot_id)) % (2**31))
        
    def reset(self):
        self.pos = self.start_pos
        self.state = "IDLE"
        self.battery = 100.0
        self.path = []
        self.current_task = None
        self.known_tasks.clear()
        self.open_bids.clear()
        self.queued_tasks.clear()
        self.wait_ticks = 0
        self.completed_tasks = 0
        self.total_wait_ticks = 0
        self.avoid_until.clear()
        self.nudged = False
        self.display_status = ""
        self.dstar_router = None
        self.last_rank = None
        self.goal_since_t, self._rank_goal = 0, None
        self.book = ReservationBook(self.robot_id)
        self.home = self._pick_home(self.pos)

    def _update_pos(self, new_pos: Cell):
        self.pos = new_pos
        if self.dstar_router:
            self.dstar_router.move_to(new_pos)

    def _parking_cell(self) -> Optional[Cell]:
        """Fleet policy (all modes, baseline included): an idle robot goes back
        to its OWN home cell -- where it started -- and stays there. Deterministic
        and tidy: the fleet keeps its formation instead of drifting across the
        floor between jobs, and nobody camps on a shared resource (a robot parked
        on or in front of a dropoff walls it off for everyone). Returns None when
        already home. Measured: same completion time as parking on the nearest
        perimeter lane, which is what this replaced."""
        if self.pos == self.home:
            return None
        taken = {it.path[0] for it in self.book.peers.values() if it.path}
        if self.home not in taken and not self.wmap.is_blocked(self.home):
            return self.home
        # somebody else is sitting on my home: settle on the nearest clear cell
        free = [(r, c) for r in range(self.wmap.rows) for c in range(self.wmap.cols)
                if self._is_out_of_the_way((r, c)) and (r, c) not in taken
                and not self.wmap.is_blocked((r, c))]
        return min(free, key=lambda cell: manhattan(self.pos, cell), default=None)

    def _is_out_of_the_way(self, cell: Cell) -> bool:
        """A cell an idle robot may sit on indefinitely: plain floor, not a shared
        resource, not the approach to one, and not inside a single-width aisle."""
        r, c = cell
        if self.wmap.grid[r][c] != FREE or cell in self.wmap.aisle_cells:
            return False
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < self.wmap.rows and 0 <= nc < self.wmap.cols                     and self.wmap.grid[nr][nc] in (PICKUP, DROPOFF, CHARGE):
                return False
        return True

    def _pick_home(self, pos: Cell) -> Cell:
        """Home is the spawn cell, unless spawning on a resource cell or in an
        aisle -- then the nearest cell an idle robot may legitimately sit on."""
        if self._is_out_of_the_way(pos):
            return pos
        cands = [(r, c) for r in range(self.wmap.rows) for c in range(self.wmap.cols)
                 if self._is_out_of_the_way((r, c))]
        return min(cands, key=lambda cell: manhattan(pos, cell), default=pos)

    def to_pibt_state(self) -> PIBTAgentState:
        """Exports agent state for L4 PIBT coordination."""
        goal = self._goal_for_state()
        if goal is None and self.state == "IDLE":
            goal = self._parking_cell()
        if goal != self._rank_goal:
            self._rank_goal, self.goal_since_t = goal, self.t
        return PIBTAgentState(
            robot_id=self.robot_id,
            pos=self.pos,
            goal=goal,
            goal_since=self.goal_since_t,
            priority_base=self.priority_base,
            path=list(self.path),
        )

    def _send_intent(self, path: List[Cell], priority: int):
        """Broadcast our short-horizon plan. Cooperative robots also share the
        goal, wait time and PIBT rank peers need for local L3/L4 decisions."""
        msg = {"type": "intent", "robot_id": self.robot_id, "priority": priority,
               "path": path, "start_t": self.t}
        if self.cooperative:
            st = self.to_pibt_state()
            self.last_rank = st.priority_key
            msg.update(goal=st.goal, rank=list(self.last_rank))
        self.send(msg)

    def _local_pibt_move(self) -> Cell:
        """L4: run PIBT over ourselves + peers within PIBT_LOCAL_RADIUS, using only
        their broadcast intents, and return OUR next cell. Every nearby robot runs
        the same rule on (nearly) the same data; the L2 shield covers any mismatch."""
        if self._goal_for_state() is not None and len(self.path) < 2:
            self._replan()
        agents = {self.robot_id: self.to_pibt_state()}
        for pid, it in self.book.peers.items():
            if not it.path or manhattan(it.path[0], self.pos) > PIBT_LOCAL_RADIUS:
                continue
            since, base = (it.rank[0], it.rank[1]) if it.rank else (it.start_t, it.priority)
            agents[pid] = PIBTAgentState(pid, it.path[0], tuple(it.goal) if it.goal else None,
                                         since, base, list(it.path))
        return run_pibt_step(agents, self.wmap)[self.robot_id]

    def _yield_if_deadlock_victim(self):
        """L3: build a wait-for graph from our own view (self + received intents).
        If we are in a cycle AND we are its deterministic victim, yield now."""
        if len(self.path) < 2:
            return
        my_since = self.last_rank[0] if self.last_rank else self.goal_since_t  # as peers saw it
        nodes = {self.robot_id: (self.pos, self.path[1], my_since, self.priority_base)}
        for pid, it in self.book.peers.items():
            if not it.path:
                continue
            nxt = it.path[1] if len(it.path) >= 2 and it.path[1] != it.path[0] else None
            since, base = (it.rank[0], it.rank[1]) if it.rank else (it.start_t, it.priority)
            nodes[pid] = (it.path[0], nxt, since, base)
        if local_deadlock_victim(self.robot_id, nodes) == self.robot_id:
            self.avoid_until[self.path[1]] = self.t + AVOID_WINDOW
            self.path = []
            self.wait_ticks = 0
            self.display_status = "DEADLOCK_RESOLVED"

    # ---------------------------------------------------------------- #
    # NETWORK: called by transport layer whenever a message arrives
    # ---------------------------------------------------------------- #
    def on_message(self, msg: dict):
        kind = msg.get("type")
        if kind == "intent":
            self.book.update(PeerIntent(
                robot_id=msg["robot_id"], priority=msg["priority"],
                path=[tuple(c) for c in msg["path"]], start_t=msg["start_t"],
                received_at=time.time(),
                goal=tuple(msg["goal"]) if msg.get("goal") else None,
                rank=tuple(msg["rank"]) if msg.get("rank") else None))
        elif kind == "task_announce":
            created_t = msg.get("t") or self.t
            task = Task(msg["task_id"], tuple(msg["pickup"]), tuple(msg["dropoff"]), created_t)
            self.known_tasks.setdefault(task.task_id, task)
        elif kind == "bid":
            self.open_bids.setdefault(msg["task_id"], {})[msg["robot_id"]] = msg["cost"]
        elif kind == "task_claimed":
            self.known_tasks.pop(msg["task_id"], None)
            if self.current_task and self.current_task.task_id == msg["task_id"] \
                    and msg["winner"] != self.robot_id:
                # someone else won a task we were also bidding on
                pass
        elif kind == "blockage":
            blk_cell = tuple(msg["cell"])
            self.wmap.report_blockage(blk_cell, msg.get("duration", 20.0))
            if config.USE_DSTAR_LITE and self.dstar_router:
                self.dstar_router.update_blockage(blk_cell, True)
                self.dstar_router.compute_shortest_path()
                self.path = self.dstar_router.extract_path()
            elif self.path and blk_cell in self.path:
                self.path = []  # force replan
        elif kind == "clear_tasks":
            # clear all known open tasks from the network
            self.known_tasks.clear()
            self.open_bids.clear()
            self.queued_tasks.clear()
            self.current_task = None
            if self.state != "CHARGING" and self.state != "EN_ROUTE_TO_CHARGE":
                self.state = "IDLE"
            self.path = []
        elif kind == "reset":
            self.reset()
        elif kind == "nudge":
            if msg.get("target") == self.robot_id and self.state == "IDLE":
                # Ignore impatient repeated nudges if we are already in the process of making way!
                if not self.path or len(self.path) < 2:
                    self.nudged = True

    # ---------------------------------------------------------------- #
    # TASK ALLOCATION -- decentralized Contract Net Protocol
    # ---------------------------------------------------------------- #
    def announce_task(self, task: Task):
        self.known_tasks[task.task_id] = task
        self.send({"type": "task_announce", "task_id": task.task_id,
                    "pickup": task.pickup, "dropoff": task.dropoff, "t": self.t})

    def bid_on_open_tasks(self):
        if self.battery < LOW_BATTERY:
            return
            
        reserved = self.book.as_reserved_table() if self.cooperative else None
        
        for task_id, task in list(self.known_tasks.items()):
            # Only bid once per task to prevent shifting bids as busy robots move!
            if task_id in self.open_bids and self.robot_id in self.open_bids[task_id]:
                continue
                
            if self.state == "IDLE":
                # 1. Compute true space-time cost to pickup
                path_to_pickup = astar(self.wmap, self.pos, task.pickup, reserved, start_t=self.t, self_id=self.robot_id)
                if not path_to_pickup:
                    continue  # Literally cannot reach pickup right now, don't bid!
                dist_to_pickup = len(path_to_pickup) - 1
                
                # 2. Compute true space-time cost from pickup to dropoff
                t_at_pickup = self.t + dist_to_pickup
                path_to_dropoff = astar(self.wmap, task.pickup, task.dropoff, reserved, start_t=t_at_pickup, self_id=self.robot_id)
                dist_to_dropoff = len(path_to_dropoff) - 1 if path_to_dropoff else manhattan(task.pickup, task.dropoff)
            else:
                # Predictive chaining: robot is currently working, but can bid on its NEXT task!
                if self.state not in ("EN_ROUTE_TO_PICKUP", "EN_ROUTE_TO_DROPOFF") or not self.current_task:
                    continue
                if len(self.queued_tasks) >= 1:
                    continue  # Only allow queuing 1 task deep to prevent monopolization
                    
                # Estimate time remaining on current task
                if self.state == "EN_ROUTE_TO_PICKUP":
                    ticks_to_finish = manhattan(self.pos, self.current_task.pickup) + manhattan(self.current_task.pickup, self.current_task.dropoff)
                else:
                    ticks_to_finish = manhattan(self.pos, self.current_task.dropoff)
                
                # A busy robot continues moving towards its goal during the 3-tick auction,
                # whereas an IDLE robot sits completely still waiting for the auction to settle.
                # We subtract those ticks to accurately compare their true arrival times!
                ticks_to_finish = max(0, ticks_to_finish - AUCTION_WINDOW_TICKS)
                    
                future_pos = self.current_task.dropoff
                
                # Distance is the time until we finish our current job + manhattan to new task
                dist_to_pickup = ticks_to_finish + manhattan(future_pos, task.pickup)
                dist_to_dropoff = manhattan(task.pickup, task.dropoff)
            
            # 3. Add battery penalty
            # Non-linear penalty: battery > 60% has 0 penalty.
            # Below 60%, penalty scales quadratically to strongly discourage low-battery robots
            # from taking tasks, while letting healthy robots bid purely on distance.
            batt_penalty = 0
            if self.battery < 60.0:
                batt_penalty = int(((60.0 - self.battery) / 10.0) ** 2)
            
            cost = dist_to_pickup + dist_to_dropoff + batt_penalty
            
            bid_msg = {"type": "bid", "task_id": task_id,
                        "robot_id": self.robot_id, "cost": cost,
                        "details": {"dist_to_pickup": dist_to_pickup, "dist_to_dropoff": dist_to_dropoff, "battery_penalty": batt_penalty}}
            self.send(bid_msg)
            # loop back to ourselves too -- the network layer correctly
            # never delivers our own broadcasts back to us (it's not our
            # own peer), but WE still need our own bid on record to
            # correctly judge whether we won the auction.
            self.on_message(bid_msg)

    def settle_auctions(self):
        """Every robot runs this SAME deterministic function on the SAME
        received bids, so all robots independently agree on the winner --
        no auctioneer needed. (If a robot's view of bids is momentarily
        incomplete because a broadcast hasn't arrived yet, the worst case
        is a brief mis-assignment that self-corrects next auction tick --
        never a collision, only a minor efficiency loss.)"""
        if config.USE_BATCHING:
            BATCH_WINDOW_TICKS = 6
            ready_tasks = [
                tid for tid, bids in self.open_bids.items()
                if self.known_tasks.get(tid) is not None
                and len(bids) > 0
                and (self.t - self.known_tasks[tid].created_t >= BATCH_WINDOW_TICKS)
            ]
            if ready_tasks:
                assignments = hungarian_batch_assign(self.open_bids, ready_tasks)
                for task_id, winner in assignments.items():
                    if winner == self.robot_id:
                        if self.state == "IDLE":
                            self.current_task = self.known_tasks.pop(task_id, None)
                            if self.current_task:
                                self.state = "EN_ROUTE_TO_PICKUP"
                                self.path = []
                                self.send({"type": "task_claimed", "task_id": task_id,
                                           "winner": self.robot_id})
                        elif self.state in ("EN_ROUTE_TO_PICKUP", "EN_ROUTE_TO_DROPOFF") \
                                and len(self.queued_tasks) < 1:
                            t_obj = self.known_tasks.pop(task_id, None)
                            if t_obj:
                                self.queued_tasks.append(t_obj)
                                self.send({"type": "task_claimed", "task_id": task_id,
                                           "winner": self.robot_id})
                    self.open_bids.pop(task_id, None)
            return

        for task_id, bids in list(self.open_bids.items()):
            task = self.known_tasks.get(task_id)
            if task is None or len(bids) == 0:
                continue
            if self.t - task.created_t < AUCTION_WINDOW_TICKS:
                continue  # auction window still open -- give peers time to bid
            winner = min(bids.items(), key=lambda kv: (kv[1], kv[0]))[0]
            if winner == self.robot_id:
                # Only take the task off the market if we can actually accept it --
                # otherwise it stays known and gets re-auctioned next tick instead of
                # silently vanishing (a robot winning several auctions at once used
                # to drop every win after the first two).
                if self.state == "IDLE":
                    self.current_task = self.known_tasks.pop(task_id)
                    self.state = "EN_ROUTE_TO_PICKUP"
                    self.path = []
                    self.send({"type": "task_claimed", "task_id": task_id,
                                "winner": self.robot_id})
                elif self.state in ("EN_ROUTE_TO_PICKUP", "EN_ROUTE_TO_DROPOFF") \
                        and len(self.queued_tasks) < 1:
                    self.queued_tasks.append(self.known_tasks.pop(task_id))
                    self.send({"type": "task_claimed", "task_id": task_id,
                                "winner": self.robot_id})
            self.open_bids.pop(task_id, None)

    # ---------------------------------------------------------------- #
    # MOTION / COLLISION AVOIDANCE
    # ---------------------------------------------------------------- #
    def _goal_for_state(self) -> Optional[Cell]:
        if self.state == "EN_ROUTE_TO_PICKUP":
            return self.current_task.pickup
        if self.state == "EN_ROUTE_TO_DROPOFF":
            return self.current_task.dropoff
        if self.state == "EN_ROUTE_TO_CHARGE":
            return min(self.wmap.charge_points, key=lambda c: manhattan(self.pos, c)) \
                if self.wmap.charge_points else None
        return None

    def _on_resource_cell(self) -> bool:
        r, c = self.pos
        return self.wmap.grid[r][c] in (PICKUP, DROPOFF, CHARGE)

    def _nearest_staging_cell(self) -> Optional[Cell]:
        """BFS out from the current position for the closest plain free
        cell. An idle robot must not permanently camp on a pickup/dropoff/
        charging cell -- that's a shared physical resource other robots
        need, exactly like a loading bay in a real warehouse."""
        seen = {self.pos}
        q = deque([self.pos])
        occupied_cells = {intent.path[0] for intent in self.book.peers.values() if intent.path}
        
        while q:
            cur = q.popleft()
            r, c = cur
            if cur != self.pos and self.wmap.grid[r][c] == FREE and cur not in occupied_cells:
                return cur
            for n in self.wmap.neighbours(cur):
                if n not in seen:
                    seen.add(n)
                    q.append(n)
        return None

    def _replan(self):
        goal = self._goal_for_state()
        if goal is None:
            self.path = []
            return

        if self.cooperative and config.USE_DSTAR_LITE and not self.avoid_until:
            if self.dstar_router is None or self.dstar_router.s_goal != goal:
                self.dstar_router = DStarLite(self.wmap, self.pos, goal)
                self.dstar_router.compute_shortest_path()
            else:
                self.dstar_router.move_to(self.pos)
                self.dstar_router.compute_shortest_path()
            self.path = self.dstar_router.extract_path()
            if self.path:
                return

        # Baseline ("stop-and-wait") robots plan blind: they never look at
        # peers' broadcast intents while planning, so they can't proactively
        # avoid future congestion -- only react once literally blocked.
        reserved = self.book.as_reserved_table() if self.cooperative else None
        if self.avoid_until:  # baseline robots also detour around a cell they timed out on
            self.display_status = "RECALCULATING"
            reserved = dict(reserved) if reserved else {}
            for cell, expiry in self.avoid_until.items():
                if expiry > self.t:
                    for dt in range(400):
                        reserved.setdefault((cell, self.t + dt), self.robot_id + "#avoid")
        congestion_map = build_congestion_heatmap(self.book) if (self.cooperative and config.USE_CONGESTION_COST) else None
        self.path = astar(self.wmap, self.pos, goal, reserved,
                            start_t=self.t, self_id=self.robot_id,
                            congestion_map=congestion_map)
        
        # If we couldn't find a path to our goal (e.g. because the goal itself 
        # is blacklisted or blocked), we should temporarily retreat to a staging cell!
        if not self.path and self.cooperative:
            target = self._nearest_staging_cell()
            if target:
                self.path = astar(self.wmap, self.pos, target, reserved,
                                  start_t=self.t, self_id=self.robot_id,
                                  congestion_map=congestion_map)
                if self.path:
                    self.display_status = "RECALCULATING"

    def step(self, next_cell_override: Optional[Cell] = None):
        """Advance simulation/reality by one tick. Call order matters:
        1) battery/state transitions  2) plan if needed  3) broadcast intent
        4) resolve local conflicts (or L4 PIBT) 5) L2 safety shield validation 6) move."""
        if self.display_status in ("RECALCULATING", "YIELDING"):
            self.display_status = ""
        
        self.t += 1
        if self.t == 1:
            # Hello tick: announce where we are before ever moving. Without it a
            # robot could drive into a peer it has not heard from yet.
            self._send_intent([self.pos] * PLAN_HORIZON, self.priority_base)
            return
        self.book.prune(now=time.time())
        if self.avoid_until:
            self.avoid_until = {c: exp for c, exp in self.avoid_until.items() if exp > self.t}

        # -- L1 Perception: FOV scan for obstacles ahead ----------------
        if self.perception and self.cooperative and len(self.path) >= 2:
            heading = (self.path[1][0] - self.pos[0], self.path[1][1] - self.pos[1])
            detections = self.perception.scan_fov(self.pos, heading, self.wmap, self.sensor_truth)
            for d in detections:
                if d.confirmed and d.cell not in self.wmap.dynamic_blocks:
                    msg = {"type": "blockage", "cell": d.cell, "duration": 30.0, "source": self.robot_id}
                    self.on_message(msg)  # same local handling as a peer alert: mark map + replan
                    self.send(msg)

        # -- battery management --------------------------------------
        if self.battery <= LOW_BATTERY and self.state not in (
                "EN_ROUTE_TO_CHARGE", "CHARGING"):
            # Remember what we were doing so a task-in-progress isn't
            # silently abandoned -- an orphaned current_task with no state
            # that ever points back to it would mean that task, and
            # whatever it was carrying, is simply lost forever.
            self._interrupted_state = self.state
            self.state = "EN_ROUTE_TO_CHARGE"
            self.path = []
        if self.state == "CHARGING":
            self.battery = min(FULL_BATTERY, self.battery + BATTERY_CHARGE_PER_TICK)
            if self.battery >= FULL_BATTERY:
                if self.current_task is not None:
                    # resume the exact leg of the task we were on
                    self.state = self._interrupted_state or "EN_ROUTE_TO_PICKUP"
                else:
                    self.state = "IDLE"
                self.path = []
            # A charging robot must keep announcing its position -- if it
            # goes silent, peers' books go stale after a few ticks and a
            # SECOND low-battery robot could target this same occupied
            # charging slot, believing it free.
            self._send_intent([self.pos] * PLAN_HORIZON, self.priority_base)
            return

        # -- state transitions on arrival ------------------------------
        goal = self._goal_for_state()
        if goal is not None and self.pos == goal:
            if self.state == "EN_ROUTE_TO_PICKUP":
                self.state = "EN_ROUTE_TO_DROPOFF"
            elif self.state == "EN_ROUTE_TO_DROPOFF":
                self.completed_tasks += 1
                if self.queued_tasks:
                    self.current_task = self.queued_tasks.pop(0)
                    self.state = "EN_ROUTE_TO_PICKUP"
                else:
                    self.current_task = None
                    self.state = "IDLE"
            elif self.state == "EN_ROUTE_TO_CHARGE":
                self.state = "CHARGING"
            self.path = []
            goal = self._goal_for_state()

        # -- L3 wait-for-graph + L4 PIBT, each decided locally by this robot --
        if self.cooperative and config.USE_WAITFOR_GRAPH:
            self._yield_if_deadlock_victim()
        if self.cooperative and config.USE_PIBT and next_cell_override is None:
            next_cell_override = self._local_pibt_move()

        # -- L4 PIBT Move ---------------------------------------------------
        if next_cell_override is not None:
            eff_priority = (apply_aging(self.wait_ticks, self.priority_base)
                             if self.cooperative else self.priority_base)
            wants_move = len(self.path) >= 2
            if (next_cell_override == self.pos and wants_move and self.wait_ticks >= PIBT_STALL_TICKS
                    and self.path[1] in self.wmap.neighbours(self.pos)):
                # Robots' local PIBT views differ slightly (different neighbours in
                # range), so two robots can each hand an EMPTY cell to the other and
                # both wait forever. After a short stall, let the L2 shield arbitrate
                # instead: its broadcast-rank rule is identical on both sides, so
                # exactly one of them proceeds.
                next_cell_override = self.path[1]
            # L2 Absolute-Occupancy Safety Shield retains final veto
            is_safe = l2_safety_shield(self.robot_id, next_cell_override, self.pos, self.book,
                                       self.wmap, self_rank=self.last_rank)
            if is_safe and next_cell_override != self.pos:
                self._update_pos(next_cell_override)
                if wants_move and self.path[1] == next_cell_override:
                    self.path = self.path[1:]
                else:
                    self.path = []  # pushed/sidestepped: stale plan, replan next tick
                self.battery = max(0.0, self.battery - BATTERY_DRAIN_PER_MOVE)
                self.wait_ticks = 0
                self.display_status = ""
            elif is_safe:
                # PIBT kept us in place: that is a wait only if we wanted to move
                if wants_move:
                    self.wait_ticks += 1
                    self.total_wait_ticks += 1
                    self.display_status = "WAITING"
                else:
                    self.wait_ticks = 0
            else:
                self.wait_ticks += 1
                self.total_wait_ticks += 1
                self.display_status = "L2_VETO"

            if self.cooperative and len(self.path) >= 2:
                horizon = [self.pos] + self.path[1:PLAN_HORIZON]
            elif self.cooperative:
                horizon = [self.pos] * PLAN_HORIZON
            else:
                horizon = [self.pos]
            self._send_intent(horizon, eff_priority)
            return

        if self.state == "IDLE":
            # Step off a pickup/dropoff/charge cell instead of camping on
            # it -- otherwise a second robot arriving at the same shared
            # resource would have nowhere to physically go.
            has_path = bool(self.path and len(self.path) >= 2)
            park = None if has_path else self._parking_cell()
            if park or self._on_resource_cell() or self.nudged or has_path:
                if self.nudged:
                    self.avoid_until[self.pos] = self.t + 10
                    self.path = []
                    self.nudged = False
                    self.display_status = "MAKING WAY"
                    
                just_planned_idle = False
                if not self.path or len(self.path) < 2:
                    target = park or self._nearest_staging_cell()
                    if target:
                        reserved = self.book.as_reserved_table() if self.cooperative else None
                        self.path = astar(self.wmap, self.pos, target, reserved,
                                            start_t=self.t, self_id=self.robot_id)
                        just_planned_idle = True
                if self.path and len(self.path) >= 2:
                    if just_planned_idle:
                        horizon = [self.pos] + self.path[1:PLAN_HORIZON]
                        self._send_intent(horizon, self.priority_base)
                        return
                    
                    next_cell = self.path[1]
                    can_go = resolve_conflict(self.robot_id, self.priority_base,
                                                next_cell, self.pos, self.book)
                    if can_go and not self.wmap.is_blocked(next_cell):
                        self._update_pos(next_cell)
                        self.path = self.path[1:]
                        self.wait_ticks = 0
                        horizon = [self.pos] + self.path[1:PLAN_HORIZON]
                    else:
                        self.wait_ticks += 1
                        if self.wait_ticks > STARVATION_WAIT_LIMIT:
                            self.avoid_until[next_cell] = self.t + AVOID_WINDOW
                            self.path = []  # try a different staging cell next tick
                            self.wait_ticks = 0
                        horizon = [self.pos] + self.path[1:PLAN_HORIZON] if self.cooperative and len(self.path) >= 2 else [self.pos] * PLAN_HORIZON
                    self._send_intent(horizon, self.priority_base)
                    return
            self._send_intent([self.pos] * PLAN_HORIZON, self.priority_base)
            return

        # -- (re)plan if we have no path --------------------------------
        just_planned = False
        if not self.path or len(self.path) < 2:
            self._replan()
            just_planned = True

        if not self.path or len(self.path) < 2:
            # boxed in -- broadcast that we're stationary and try again next tick
            self._send_intent([self.pos] * PLAN_HORIZON, self.priority_base)
            return

        eff_priority = (apply_aging(self.wait_ticks, self.priority_base)
                         if self.cooperative else self.priority_base)

        # -- reactive collision check against peers we've heard from ------
        # (evaluated BEFORE broadcasting -- see note below on ordering)
        next_cell = self.path[1]
        if just_planned:
            moved = False
        else:
            can_go = resolve_conflict(self.robot_id, eff_priority, next_cell,
                                        self.pos, self.book)
    
            if can_go and not self.wmap.is_blocked(next_cell):
                self._update_pos(next_cell)
                self.path = self.path[1:]
                self.battery = max(0.0, self.battery - BATTERY_DRAIN_PER_MOVE)
                self.wait_ticks = 0
                self.display_status = ""
                moved = True
            else:
                self.wait_ticks += 1
                self.total_wait_ticks += 1
                moved = False
                
                # Determine EXACTLY why we failed collision check for telemetry
                block_reason = "OCCUPIED"
                blocker = None
                peer_prio = 0
                for peer_id, intent in self.book.peers.items():
                    if intent.path and intent.path[0] == next_cell:
                        blocker = peer_id
                        break
                
                if not blocker:
                    # Not physically occupied, so we must have lost a priority race
                    for peer_id, intent in self.book.peers.items():
                        if len(intent.path) >= 2 and intent.path[1] == next_cell and intent.path[0] != next_cell:
                            if (eff_priority, self.robot_id) > (intent.priority, peer_id):
                                blocker = peer_id
                                block_reason = "YIELD_PRIORITY"
                                peer_prio = intent.priority
                                break
                                
                if block_reason == "YIELD_PRIORITY":
                    self.display_status = f"YIELDING|{blocker}|{next_cell[0]},{next_cell[1]}|{eff_priority}|{peer_prio}"
                else:
                    self.display_status = "WAITING"
                
                
                # NUDGE PROTOCOL: If we are blocked by a peer sitting directly on next_cell, ask them to move!
                # We send the nudge every 2 ticks to ensure it gets through but doesn't spam.
                if self.cooperative and self.wait_ticks % 2 == 1:
                    blocker = None
                    for peer_id, intent in self.book.peers.items():
                        if intent.path and intent.path[0] == next_cell:
                            blocker = peer_id
                            break
                    if blocker:
                        self.send({"type": "nudge", "target": blocker, "from": self.robot_id})
                        self.display_status = "ASKING TO MOVE"
                
                # Break symmetry in head-to-head deadlocks: lower priority (higher index)
                # robots have a shorter starvation limit, so they yield and back up first!
                dynamic_starvation_limit = 10 + (5 - self.priority_base) * 4
                if self.cooperative and self.wait_ticks > dynamic_starvation_limit:
                    # break the deadlock: force a fresh plan (often finds a
                    # detour if the previous path is hopelessly congested)
                    self.avoid_until[next_cell] = self.t + AVOID_WINDOW
                    self.path = []
                    self.wait_ticks = 0
                elif not self.cooperative and \
                        self.wait_ticks > BASELINE_WAIT_TIMEOUT + 2 * (self.priority_base % 5):
                    # Stop-and-wait with timeout: after waiting, detour around the
                    # blocked cell. Staggered per robot (like Ethernet backoff) so two
                    # robots stuck head-on do not both give up on the same tick.
                    self.avoid_until[next_cell] = self.t + AVOID_WINDOW
                    self.path = []
                    self.wait_ticks = 0
            # NOTE: baseline robots intentionally do nothing else here --
            # they just keep re-checking the same static path next tick,
            # which is exactly what makes "stop-and-wait" slow at busy
            # choke points: no rerouting, no negotiated priority beyond
            # the bare swap-deadlock tie-break inside resolve_conflict().

        # -- broadcast intent AFTER the move decision ---------------------
        if self.cooperative and len(self.path) >= 2:
            horizon = [self.pos] + self.path[1:PLAN_HORIZON]
        elif self.cooperative:
            horizon = [self.pos] * PLAN_HORIZON
        else:
            horizon = [self.pos]
        self._send_intent(horizon, eff_priority)
