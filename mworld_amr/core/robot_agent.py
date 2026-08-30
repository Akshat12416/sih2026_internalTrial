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
from core.planner import (WarehouseMap, astar, ReservationBook, PeerIntent,
                           resolve_conflict, apply_aging, Cell, manhattan,
                           FREE, PICKUP, DROPOFF, CHARGE)

PLAN_HORIZON = 6           # how many future steps a robot broadcasts as "intent"
LOW_BATTERY = 20.0
FULL_BATTERY = 100.0
BATTERY_DRAIN_PER_MOVE = 0.35
BATTERY_CHARGE_PER_TICK = 8.0
STARVATION_WAIT_LIMIT = 6
AVOID_WINDOW = 15          # ticks a just-contested cell is treated as a
                            # soft no-go by THIS robot's own planner after a
                            # starvation-triggered replan -- without this, a
                            # fresh astar search over an unchanged map simply
                            # re-discovers the identical (still-blocked)
                            # shortest path, producing a livelock where the
                            # robot "replans" forever without ever actually
                            # trying a different route
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
    book: ReservationBook = field(init=False)
    wait_ticks: int = 0
    t: int = 0                              # local logical clock
    completed_tasks: int = 0
    total_wait_ticks: int = 0
    _interrupted_state: Optional[str] = field(default=None, repr=False)
    avoid_until: Dict[Cell, int] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self.book = ReservationBook(self.robot_id)

    # ---------------------------------------------------------------- #
    # NETWORK: called by transport layer whenever a message arrives
    # ---------------------------------------------------------------- #
    def on_message(self, msg: dict):
        kind = msg.get("type")
        if kind == "intent":
            self.book.update(PeerIntent(
                robot_id=msg["robot_id"], priority=msg["priority"],
                path=[tuple(c) for c in msg["path"]], start_t=msg["start_t"],
                received_at=msg["start_t"]))
        elif kind == "task_announce":
            task = Task(msg["task_id"], tuple(msg["pickup"]), tuple(msg["dropoff"]), msg["t"])
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
            self.wmap.report_blockage(tuple(msg["cell"]), msg.get("duration", 20.0))
            if self.path and tuple(msg["cell"]) in self.path:
                self.path = []  # force replan

    # ---------------------------------------------------------------- #
    # TASK ALLOCATION -- decentralized Contract Net Protocol
    # ---------------------------------------------------------------- #
    def announce_task(self, task: Task):
        self.known_tasks[task.task_id] = task
        self.send({"type": "task_announce", "task_id": task.task_id,
                    "pickup": task.pickup, "dropoff": task.dropoff, "t": self.t})

    def bid_on_open_tasks(self):
        if self.state != "IDLE" or self.battery < LOW_BATTERY:
            return
        for task_id, task in list(self.known_tasks.items()):
            cost = manhattan(self.pos, task.pickup)
            bid_msg = {"type": "bid", "task_id": task_id,
                        "robot_id": self.robot_id, "cost": cost}
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
        for task_id, bids in list(self.open_bids.items()):
            task = self.known_tasks.get(task_id)
            if task is None or len(bids) == 0:
                continue
            if self.t - task.created_t < AUCTION_WINDOW_TICKS:
                continue  # auction window still open -- give peers time to bid
            winner = min(bids.items(), key=lambda kv: (kv[1], kv[0]))[0]
            if winner == self.robot_id and self.state == "IDLE":
                task = self.known_tasks.pop(task_id, None)
                if task:
                    self.current_task = task
                    self.state = "EN_ROUTE_TO_PICKUP"
                    self.path = []
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
        while q:
            cur = q.popleft()
            r, c = cur
            if cur != self.pos and self.wmap.grid[r][c] == FREE:
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
        # Baseline ("stop-and-wait") robots plan blind: they never look at
        # peers' broadcast intents while planning, so they can't proactively
        # avoid future congestion -- only react once literally blocked.
        reserved = self.book.as_reserved_table() if self.cooperative else None
        if self.cooperative and self.avoid_until:
            reserved = dict(reserved) if reserved else {}
            for cell, expiry in self.avoid_until.items():
                if expiry > self.t and cell != goal:  # never blacklist the goal itself
                    for dt in range(0, AVOID_WINDOW):
                        reserved.setdefault((cell, self.t + dt), self.robot_id + "#avoid")
        self.path = astar(self.wmap, self.pos, goal, reserved,
                            start_t=self.t, self_id=self.robot_id)

    def step(self):
        """Advance simulation/reality by one tick. Call order matters:
        1) battery/state transitions  2) plan if needed  3) broadcast intent
        4) resolve local conflicts    5) move (or yield)."""
        self.t += 1
        self.book.prune(now=self.t)
        if self.avoid_until:
            self.avoid_until = {c: exp for c, exp in self.avoid_until.items() if exp > self.t}

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
            self.send({"type": "intent", "robot_id": self.robot_id,
                        "priority": self.priority_base, "path": [self.pos] * PLAN_HORIZON,
                        "start_t": self.t})
            return

        # -- state transitions on arrival ------------------------------
        goal = self._goal_for_state()
        if goal is not None and self.pos == goal:
            if self.state == "EN_ROUTE_TO_PICKUP":
                self.state = "EN_ROUTE_TO_DROPOFF"
            elif self.state == "EN_ROUTE_TO_DROPOFF":
                self.completed_tasks += 1
                self.current_task = None
                self.state = "IDLE"
            elif self.state == "EN_ROUTE_TO_CHARGE":
                self.state = "CHARGING"
            self.path = []
            goal = self._goal_for_state()

        if self.state == "IDLE":
            # Step off a pickup/dropoff/charge cell instead of camping on
            # it -- otherwise a second robot arriving at the same shared
            # resource would have nowhere to physically go.
            if self._on_resource_cell():
                if not self.path or len(self.path) < 2:
                    target = self._nearest_staging_cell()
                    if target:
                        reserved = self.book.as_reserved_table() if self.cooperative else None
                        self.path = astar(self.wmap, self.pos, target, reserved,
                                            start_t=self.t, self_id=self.robot_id)
                if self.path and len(self.path) >= 2:
                    next_cell = self.path[1]
                    can_go = resolve_conflict(self.robot_id, self.priority_base,
                                                next_cell, self.pos, self.book)
                    if can_go and not self.wmap.is_blocked(next_cell, now=self.t):
                        self.pos = next_cell
                        self.path = self.path[1:]
                        self.wait_ticks = 0
                        horizon = [self.pos] + self.path[1:PLAN_HORIZON]
                    else:
                        self.wait_ticks += 1
                        if self.wait_ticks > STARVATION_WAIT_LIMIT:
                            self.avoid_until[next_cell] = self.t + AVOID_WINDOW
                            self.path = []  # try a different staging cell next tick
                            self.wait_ticks = 0
                        horizon = [self.pos] * PLAN_HORIZON  # honestly stuck -- don't over-promise
                    self.send({"type": "intent", "robot_id": self.robot_id,
                                "priority": self.priority_base, "path": horizon,
                                "start_t": self.t})
                    return
            self.send({"type": "intent", "robot_id": self.robot_id,
                        "priority": self.priority_base, "path": [self.pos] * PLAN_HORIZON,  # reserve a forward window while stationary
                        "start_t": self.t})
            return

        # -- (re)plan if we have no path --------------------------------
        if not self.path or len(self.path) < 2:
            self._replan()

        if not self.path or len(self.path) < 2:
            # boxed in -- broadcast that we're stationary and try again next tick
            self.send({"type": "intent", "robot_id": self.robot_id,
                        "priority": self.priority_base, "path": [self.pos] * PLAN_HORIZON,  # reserve a forward window while stationary
                        "start_t": self.t})
            return

        # -- reactive collision check against peers we've heard from ------
        # (evaluated BEFORE broadcasting -- see note below on ordering)
        next_cell = self.path[1]
        eff_priority = (apply_aging(self.wait_ticks, self.priority_base)
                         if self.cooperative else self.priority_base)
        can_go = resolve_conflict(self.robot_id, eff_priority, next_cell,
                                    self.pos, self.book)

        if can_go and not self.wmap.is_blocked(next_cell, now=self.t):
            self.pos = next_cell
            self.path = self.path[1:]
            self.battery = max(0.0, self.battery - BATTERY_DRAIN_PER_MOVE)
            self.wait_ticks = 0
            moved = True
        else:
            self.wait_ticks += 1
            self.total_wait_ticks += 1
            moved = False
            if self.cooperative and self.wait_ticks > STARVATION_WAIT_LIMIT:
                # break the deadlock: force a fresh plan (often finds a
                # side-step around the blocking robot instead of just waiting)
                self.avoid_until[next_cell] = self.t + AVOID_WINDOW
                self.path = []
                self.wait_ticks = 0
            # NOTE: baseline robots intentionally do nothing else here --
            # they just keep re-checking the same static path next tick,
            # which is exactly what makes "stop-and-wait" slow at busy
            # choke points: no rerouting, no negotiated priority beyond
            # the bare swap-deadlock tie-break inside resolve_conflict().

        # -- broadcast intent AFTER the move decision ---------------------
        # Critical ordering: this message must describe where we TRULY are
        # right now (self.pos, already updated above if we moved) rather
        # than where we were before deciding. A peer processed later this
        # same tick -- or next tick -- must never plan against a stale,
        # unconfirmed position; that mismatch is exactly what produces
        # phantom "vacates that never happened" collisions.
        #
        # And critically: if we just got YIELDED/blocked, we must NOT keep
        # optimistically broadcasting our full intended route as if we're
        # about to sail through it -- that falsely tells peers our current
        # cell frees up next tick, when in fact we're still sitting in it.
        # A stuck robot honestly reserves its OWN cell across the whole
        # horizon instead, so peers' proactive planning routes around us
        # for real rather than walking straight at us on a false promise.
        if moved and self.cooperative:
            horizon = [self.pos] + self.path[1:PLAN_HORIZON]
        elif self.cooperative:
            horizon = [self.pos] * PLAN_HORIZON
        else:
            horizon = [self.pos]
        self.send({"type": "intent", "robot_id": self.robot_id,
                    "priority": eff_priority, "path": horizon, "start_t": self.t})
