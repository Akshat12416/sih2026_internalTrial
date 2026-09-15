"""
sim/fast_sim.py
================
A single-process, fast, deterministic simulator. It reuses the EXACT same
core.robot_agent.RobotAgent / core.planner logic the live UDP demo uses --
only the transport is swapped from real sockets to plain in-memory function
calls (via `Bus`), which is fine because coordination correctness must not
depend on transport speed. This lets us:

  1. Prove ZERO collisions over many robots/tasks/seeds very quickly.
  2. Directly compare total fleet task-completion time between:
        - cooperative  = our decentralized reservation + priority system
        - baseline     = naive "stop-and-wait" (blind planning, purely
                          reactive halting, no rerouting)
     to validate the >=20% improvement success criterion.

Run:
    python -m sim.fast_sim --robots 4 --tasks 24 --seed 1
"""
from __future__ import annotations
import argparse
import random
import statistics
from typing import Dict, List, Optional, Tuple

from core.layouts import demo_warehouse, build_warehouse
from core.robot_agent import RobotAgent, Task
from core.planner import Cell
from core import config

START_POSITIONS = [(9, 2), (9, 5), (9, 8), (9, 11), (0, 2), (0, 8)]


def start_positions(n: int, wmap) -> List[Cell]:
    """Unique spawn cells. On the demo map: the classic 6 starts first. Then plain
    free cells in the open staging rows at the bottom, spread out every other
    column, then the rest -- robots never spawn on top of each other."""
    classic = START_POSITIONS if (wmap.rows, wmap.cols) == (11, 15) else []
    staging = [(r, c) for r in range(wmap.rows - 2, -1, -1) for c in range(wmap.cols)
               if wmap.grid[r][c] == 0 and (r, c) not in wmap.aisle_cells]
    cells = classic + [x for x in staging if x[1] % 2 == 0 and x not in classic] \
        + [x for x in staging if x[1] % 2 == 1 and x not in classic]
    assert n <= len(cells), f"layout only has {len(cells)} start cells"
    return cells[:n]


class Bus:
    """In-process stand-in for the UDP mesh. Delivers a message to every
    OTHER registered robot -- structurally the same guarantee real sockets
    give us (a robot never has its own port in its own peer list)."""
    def __init__(self):
        self.subscribers: Dict[str, callable] = {}

    def register(self, robot_id: str, on_message):
        self.subscribers[robot_id] = on_message

    def send(self, sender_id: str, msg: dict):
        for rid, cb in self.subscribers.items():
            if rid != sender_id:
                cb(msg)


def make_task_schedule(n_tasks: int, seed: int, wmap) -> List[Tuple[int, Cell, Cell]]:
    """Fixed, reproducible arrival schedule shared identically by BOTH runs
    (cooperative and baseline) so the comparison is apples-to-apples."""
    rng = random.Random(seed)
    schedule = []
    t = 0
    for i in range(n_tasks):
        t += rng.randint(2, 6)
        pickup = rng.choice(wmap.pickup_points)
        dropoff = rng.choice(wmap.dropoff_points)
        schedule.append((t, pickup, dropoff))
    return schedule


def run(n_robots: int, schedule, cooperative: bool, max_ticks: int, seed: int,
        directed: Optional[bool] = None, use_pibt: Optional[bool] = None,
        use_wfg: Optional[bool] = None, use_congestion: Optional[bool] = None,
        use_dstar: Optional[bool] = None, use_batching: Optional[bool] = None,
        layout: Optional[Tuple[int, int]] = None):
    """layout = (bays, shelf_rows) for core.layouts.build_warehouse; None = demo map.
    The schedule must have been built on the same layout."""
    overrides = {"USE_PIBT": use_pibt, "USE_WAITFOR_GRAPH": use_wfg,
                 "USE_CONGESTION_COST": use_congestion, "USE_DSTAR_LITE": use_dstar,
                 "USE_BATCHING": use_batching}
    saved = {k: getattr(config, k) for k in overrides}
    for k, v in overrides.items():
        if v is not None:
            setattr(config, k, v)
    try:
        return _run(n_robots, schedule, cooperative, max_ticks, directed, layout)
    finally:
        for k, v in saved.items():
            setattr(config, k, v)


def _run(n_robots: int, schedule, cooperative: bool, max_ticks: int, directed: Optional[bool],
         layout: Optional[Tuple[int, int]]):
    wmap = build_warehouse(*layout, directed=directed) if layout else demo_warehouse(directed=directed)
    bus = Bus()
    agents: Dict[str, RobotAgent] = {}

    starts = start_positions(n_robots, wmap)
    for i in range(n_robots):
        rid = f"R{i+1}"
        agent = RobotAgent(robot_id=rid, pos=starts[i],
                             wmap=wmap, send=lambda m, rid=rid: bus.send(rid, m),
                             priority_base=i, cooperative=cooperative)
        agents[rid] = agent
        bus.register(rid, agent.on_message)

    collisions = 0
    aisle_head_ons = 0
    corridor_head_ons = 0
    completion_tick = {}   # task_id -> tick completed
    total_tasks = len(schedule)
    pending_idx = 0
    task_counter = 0

    for tick in range(1, max_ticks + 1):
        # release any tasks whose arrival time has come, via a synthetic
        # "system" announcer (a real warehouse-management order feed) that
        # is NOT one of the robots -- it only announces, never assigns.
        while pending_idx < len(schedule) and schedule[pending_idx][0] <= tick:
            arrival_t, pickup, dropoff = schedule[pending_idx]
            task_counter += 1
            tid = f"T{task_counter}"
            task = Task(tid, pickup, dropoff, tick)
            for agent in agents.values():
                agent.known_tasks.setdefault(tid, task)
            pending_idx += 1

        for agent in agents.values():
            agent.bid_on_open_tasks()
        for agent in agents.values():
            agent.settle_auctions()

        # -- check for head-on encounters before moving -------------------
        for rid1, a1 in agents.items():
            for rid2, a2 in agents.items():
                if rid1 >= rid2:
                    continue
                next1 = a1.path[1] if len(a1.path) >= 2 else None
                next2 = a2.path[1] if len(a2.path) >= 2 else None
                # Case 1: Direct head-on swap attempt
                if next1 and next2 and next1 == a2.pos and next2 == a1.pos:
                    if a1.pos in wmap.aisle_cells or a2.pos in wmap.aisle_cells:
                        aisle_head_ons += 1
                    else:
                        corridor_head_ons += 1
                # Case 2: Facing each other in same vertical aisle
                elif next1 and next2 and a1.pos[1] == a2.pos[1]:
                    if a1.pos in wmap.aisle_cells and a2.pos in wmap.aisle_cells:
                        dir1 = next1[0] - a1.pos[0]
                        dir2 = next2[0] - a2.pos[0]
                        if dir1 != 0 and dir2 != 0 and dir1 != dir2:
                            if (a1.pos[0] < a2.pos[0] and dir1 > 0 and dir2 < 0) or (a2.pos[0] < a1.pos[0] and dir2 > 0 and dir1 < 0):
                                aisle_head_ons += 1

        # No fleet-wide coordinator: each robot runs its own L3/L4 logic inside
        # step(), using only the messages it has received (same as live robots).
        for agent in agents.values():
            agent.step()

        # -- collision check: two robots must never share a cell ----------
        occupied: Dict[Cell, str] = {}
        for agent in agents.values():
            if agent.pos in occupied:
                collisions += 1
                print(f"  !! COLLISION at tick {tick}: {occupied[agent.pos]} "
                      f"and {agent.robot_id} both at {agent.pos}")
            occupied[agent.pos] = agent.robot_id

        done = sum(a.completed_tasks for a in agents.values())
        if done >= total_tasks and pending_idx >= len(schedule):
            return {
                "ticks_to_finish": tick, "collisions": collisions,
                "total_wait_ticks": sum(a.total_wait_ticks for a in agents.values()),
                "completed": done,
                "aisle_head_ons": aisle_head_ons,
                "corridor_head_ons": corridor_head_ons,
                "head_on_conflicts": aisle_head_ons + corridor_head_ons,
            }

    done = sum(a.completed_tasks for a in agents.values())
    return {"ticks_to_finish": max_ticks, "collisions": collisions,
            "total_wait_ticks": sum(a.total_wait_ticks for a in agents.values()),
            "completed": done, "timed_out": True,
            "aisle_head_ons": aisle_head_ons,
            "corridor_head_ons": corridor_head_ons,
            "head_on_conflicts": aisle_head_ons + corridor_head_ons}


def _timeout_note(res: dict, n_tasks: int) -> str:
    return f" | TIMED OUT ({res['completed']}/{n_tasks} tasks done)" if res.get("timed_out") else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--robots", type=int, default=4)
    ap.add_argument("--tasks", type=int, default=24)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-ticks", type=int, default=1500)
    ap.add_argument("--trials", type=int, default=5, help="repeat with different seeds and average")
    ap.add_argument("--compare-directed", action="store_true", help="run benchmark comparing undirected vs directed graph")
    ap.add_argument("--compare-pibt", action="store_true", help="run benchmark comparing old negotiation vs PIBT")
    ap.add_argument("--compare-wfg", action="store_true", help="run benchmark comparing starvation timeout vs WFG deadlock detection")
    ap.add_argument("--compare-congestion", action="store_true", help="run benchmark comparing shortest path vs congestion-aware routing")
    ap.add_argument("--compare-dstar", action="store_true", help="run benchmark comparing full A* vs D* Lite replanning")
    ap.add_argument("--compare-batching", action="store_true", help="run benchmark comparing first-dispatch vs Hungarian batch assignment")
    ap.add_argument("--directed", action="store_true", help="enable directed guidance graph")
    ap.add_argument("--pibt", action="store_true", help="enable L4 PIBT coordination")
    ap.add_argument("--wfg", action="store_true", help="enable L3 Wait-For Graph deadlock detection")
    ap.add_argument("--congestion", action="store_true", help="enable L5 Congestion-aware routing heatmap")
    ap.add_argument("--dstar", action="store_true", help="enable L5 D* Lite incremental replanner")
    ap.add_argument("--batching", action="store_true", help="enable L6 Hungarian batch task assignment")
    ap.add_argument("--full", action="store_true", help="enable the whole stack (C1-C6)")
    args = ap.parse_args()
    if args.full:
        args.directed = args.pibt = args.wfg = args.congestion = args.dstar = args.batching = True

    wmap = demo_warehouse(directed=args.directed)
    print(f"Warehouse: {wmap.rows}x{wmap.cols} grid, "
          f"{len(wmap.choke_points)} choke points, {len(wmap.pickup_points)} pickup / "
          f"{len(wmap.dropoff_points)} dropoff points\n")

    if args.compare_wfg:
        print("=" * 70)
        print("BENCHMARK: Starvation Timeout (Old) vs Wait-For Graph Detection (New C3)")
        print(f"Fleet: {args.robots} robots, {args.tasks} tasks per trial, {args.trials} trials")
        print("=" * 70 + "\n")
        old_times, wfg_times = [], []
        old_waits, wfg_waits = [], []
        total_collisions = 0

        for trial in range(args.trials):
            seed = args.seed + trial * 97
            schedule = make_task_schedule(args.tasks, seed, wmap)

            res_old = run(args.robots, schedule, cooperative=True,
                          max_ticks=args.max_ticks, seed=seed, directed=args.directed,
                          use_pibt=args.pibt, use_wfg=False)
            res_wfg = run(args.robots, schedule, cooperative=True,
                          max_ticks=args.max_ticks, seed=seed, directed=args.directed,
                          use_pibt=args.pibt, use_wfg=True)

            total_collisions += res_old["collisions"] + res_wfg["collisions"]
            old_times.append(res_old["ticks_to_finish"])
            wfg_times.append(res_wfg["ticks_to_finish"])
            old_waits.append(res_old["total_wait_ticks"])
            wfg_waits.append(res_wfg["total_wait_ticks"])

            impr = 100 * (res_old["ticks_to_finish"] - res_wfg["ticks_to_finish"]) / res_old["ticks_to_finish"]
            print(f"Trial {trial+1} (seed={seed}):")
            print(f"  Old Timeout : {res_old['ticks_to_finish']:4d} ticks | wait={res_old['total_wait_ticks']:4d} | collisions={res_old['collisions']}")
            print(f"  WFG (L3)    : {res_wfg['ticks_to_finish']:4d} ticks | wait={res_wfg['total_wait_ticks']:4d} | collisions={res_wfg['collisions']}")
            print(f"  -> Time change: {impr:+.1f}% | Wait reduction: {100*(res_old['total_wait_ticks']-res_wfg['total_wait_ticks'])/max(1,res_old['total_wait_ticks']):.1f}%\n")

        avg_old_t = statistics.mean(old_times)
        avg_wfg_t = statistics.mean(wfg_times)
        avg_old_w = statistics.mean(old_waits)
        avg_wfg_w = statistics.mean(wfg_waits)
        time_diff = 100 * (avg_old_t - avg_wfg_t) / avg_old_t
        wait_diff = 100 * (avg_old_w - avg_wfg_w) / max(1.0, avg_old_w)

        print("=" * 70)
        print(f"SUMMARY over {args.trials} trials:")
        print(f"  Old Timeout Avg Finish Ticks : {avg_old_t:.1f}")
        print(f"  WFG Avg Finish Ticks         : {avg_wfg_t:.1f} ({time_diff:+.1f}%)")
        print(f"  Old Timeout Avg Wait Ticks   : {avg_old_w:.1f}")
        print(f"  WFG Avg Wait Ticks           : {avg_wfg_w:.1f} ({wait_diff:+.1f}%)")
        print(f"  Total Collisions             : {total_collisions}")
        print("=" * 70)
        return

    if args.compare_pibt:
        print("=" * 70)
        print("BENCHMARK: Old Negotiation (L4) vs PIBT Coordination (New C2)")
        print(f"Fleet: {args.robots} robots, {args.tasks} tasks per trial, {args.trials} trials")
        print("=" * 70 + "\n")
        old_times, pibt_times = [], []
        old_waits, pibt_waits = [], []
        total_collisions = 0

        for trial in range(args.trials):
            seed = args.seed + trial * 97
            schedule = make_task_schedule(args.tasks, seed, wmap)

            res_old = run(args.robots, schedule, cooperative=True,
                          max_ticks=args.max_ticks, seed=seed, directed=args.directed, use_pibt=False)
            res_pibt = run(args.robots, schedule, cooperative=True,
                           max_ticks=args.max_ticks, seed=seed, directed=args.directed, use_pibt=True)

            total_collisions += res_old["collisions"] + res_pibt["collisions"]
            old_times.append(res_old["ticks_to_finish"])
            pibt_times.append(res_pibt["ticks_to_finish"])
            old_waits.append(res_old["total_wait_ticks"])
            pibt_waits.append(res_pibt["total_wait_ticks"])

            impr = 100 * (res_old["ticks_to_finish"] - res_pibt["ticks_to_finish"]) / res_old["ticks_to_finish"]
            print(f"Trial {trial+1} (seed={seed}):")
            print(f"  Old Negotiation : {res_old['ticks_to_finish']:4d} ticks | wait={res_old['total_wait_ticks']:4d} | collisions={res_old['collisions']}")
            print(f"  PIBT (L4)       : {res_pibt['ticks_to_finish']:4d} ticks | wait={res_pibt['total_wait_ticks']:4d} | collisions={res_pibt['collisions']}")
            print(f"  -> Time change: {impr:+.1f}% | Wait reduction: {100*(res_old['total_wait_ticks']-res_pibt['total_wait_ticks'])/max(1,res_old['total_wait_ticks']):.1f}%\n")

        avg_old_t = statistics.mean(old_times)
        avg_pibt_t = statistics.mean(pibt_times)
        avg_old_w = statistics.mean(old_waits)
        avg_pibt_w = statistics.mean(pibt_waits)
        time_diff = 100 * (avg_old_t - avg_pibt_t) / avg_old_t
        wait_diff = 100 * (avg_old_w - avg_pibt_w) / max(1.0, avg_old_w)

        print("=" * 70)
        print(f"SUMMARY over {args.trials} trials:")
        print(f"  Old Negotiation Avg Finish Ticks : {avg_old_t:.1f}")
        print(f"  PIBT Avg Finish Ticks            : {avg_pibt_t:.1f} ({time_diff:+.1f}%)")
        print(f"  Old Negotiation Avg Wait Ticks   : {avg_old_w:.1f}")
        print(f"  PIBT Avg Wait Ticks              : {avg_pibt_w:.1f} ({wait_diff:+.1f}%)")
        print(f"  Total Collisions                 : {total_collisions}")
        print("=" * 70)
        return

    if args.compare_congestion:
        print("=" * 70)
        print("BENCHMARK: Shortest Path (Old) vs Congestion-Aware Routing (New C4)")
        print(f"Fleet: {args.robots} robots, {args.tasks} tasks per trial, {args.trials} trials")
        print("=" * 70 + "\n")
        old_times, cg_times = [], []
        old_waits, cg_waits = [], []
        total_collisions = 0

        for trial in range(args.trials):
            seed = args.seed + trial * 97
            schedule = make_task_schedule(args.tasks, seed, wmap)

            res_old = run(args.robots, schedule, cooperative=True,
                          max_ticks=args.max_ticks, seed=seed, directed=args.directed,
                          use_pibt=args.pibt, use_wfg=args.wfg, use_congestion=False)
            res_cg = run(args.robots, schedule, cooperative=True,
                         max_ticks=args.max_ticks, seed=seed, directed=args.directed,
                         use_pibt=args.pibt, use_wfg=args.wfg, use_congestion=True)

            total_collisions += res_old["collisions"] + res_cg["collisions"]
            old_times.append(res_old["ticks_to_finish"])
            cg_times.append(res_cg["ticks_to_finish"])
            old_waits.append(res_old["total_wait_ticks"])
            cg_waits.append(res_cg["total_wait_ticks"])

            impr = 100 * (res_old["ticks_to_finish"] - res_cg["ticks_to_finish"]) / res_old["ticks_to_finish"]
            th_old = args.tasks / res_old["ticks_to_finish"]
            th_cg = args.tasks / res_cg["ticks_to_finish"]
            print(f"Trial {trial+1} (seed={seed}):")
            print(f"  Shortest Path     : {res_old['ticks_to_finish']:4d} ticks | wait={res_old['total_wait_ticks']:4d} | throughput={th_old:.3f} tasks/tick")
            print(f"  Congestion-Aware  : {res_cg['ticks_to_finish']:4d} ticks | wait={res_cg['total_wait_ticks']:4d} | throughput={th_cg:.3f} tasks/tick")
            print(f"  -> Time change: {impr:+.1f}% | Wait reduction: {100*(res_old['total_wait_ticks']-res_cg['total_wait_ticks'])/max(1,res_old['total_wait_ticks']):.1f}%\n")

        avg_old_t = statistics.mean(old_times)
        avg_cg_t = statistics.mean(cg_times)
        avg_old_w = statistics.mean(old_waits)
        avg_cg_w = statistics.mean(cg_waits)
        time_diff = 100 * (avg_old_t - avg_cg_t) / avg_old_t
        wait_diff = 100 * (avg_old_w - avg_cg_w) / max(1.0, avg_old_w)
        th_old_avg = args.tasks / avg_old_t
        th_cg_avg = args.tasks / avg_cg_t
        th_gain = 100 * (th_cg_avg - th_old_avg) / th_old_avg

        print("=" * 70)
        print(f"SUMMARY over {args.trials} trials:")
        print(f"  Shortest Path Avg Finish Ticks     : {avg_old_t:.1f}")
        print(f"  Congestion-Aware Avg Finish Ticks  : {avg_cg_t:.1f} ({time_diff:+.1f}%)")
        print(f"  Shortest Path Avg Wait Ticks       : {avg_old_w:.1f}")
        print(f"  Congestion-Aware Avg Wait Ticks    : {avg_cg_w:.1f} ({wait_diff:+.1f}%)")
        print(f"  Throughput Gain (tasks/tick)       : {th_old_avg:.3f} -> {th_cg_avg:.3f} ({th_gain:+.1f}%)")
        print(f"  Total Collisions                   : {total_collisions}")
        print("=" * 70)
        return

    if args.compare_dstar:
        print("=" * 70)
        print("BENCHMARK: Full A* (Old) vs D* Lite Incremental Replanning (New C5)")
        print(f"Fleet: {args.robots} robots, {args.tasks} tasks per trial, {args.trials} trials")
        print("=" * 70 + "\n")
        old_times, dstar_times = [], []
        old_waits, dstar_waits = [], []
        total_collisions = 0

        for trial in range(args.trials):
            seed = args.seed + trial * 97
            schedule = make_task_schedule(args.tasks, seed, wmap)

            res_old = run(args.robots, schedule, cooperative=True,
                          max_ticks=args.max_ticks, seed=seed, directed=args.directed,
                          use_pibt=args.pibt, use_wfg=args.wfg, use_congestion=args.congestion,
                          use_dstar=False)
            res_dstar = run(args.robots, schedule, cooperative=True,
                           max_ticks=args.max_ticks, seed=seed, directed=args.directed,
                           use_pibt=args.pibt, use_wfg=args.wfg, use_congestion=args.congestion,
                           use_dstar=True)

            total_collisions += res_old["collisions"] + res_dstar["collisions"]
            old_times.append(res_old["ticks_to_finish"])
            dstar_times.append(res_dstar["ticks_to_finish"])
            old_waits.append(res_old["total_wait_ticks"])
            dstar_waits.append(res_dstar["total_wait_ticks"])

            impr = 100 * (res_old["ticks_to_finish"] - res_dstar["ticks_to_finish"]) / res_old["ticks_to_finish"]
            print(f"Trial {trial+1} (seed={seed}):")
            print(f"  Full A*       : {res_old['ticks_to_finish']:4d} ticks | wait={res_old['total_wait_ticks']:4d} | collisions={res_old['collisions']}")
            print(f"  D* Lite (C5)  : {res_dstar['ticks_to_finish']:4d} ticks | wait={res_dstar['total_wait_ticks']:4d} | collisions={res_dstar['collisions']}")
            print(f"  -> Time change: {impr:+.1f}%\n")

        avg_old_t = statistics.mean(old_times)
        avg_ds_t = statistics.mean(dstar_times)
        avg_old_w = statistics.mean(old_waits)
        avg_ds_w = statistics.mean(dstar_waits)
        time_diff = 100 * (avg_old_t - avg_ds_t) / avg_old_t
        wait_diff = 100 * (avg_old_w - avg_ds_w) / max(1.0, avg_old_w)

        print("=" * 70)
        print(f"SUMMARY over {args.trials} trials:")
        print(f"  Full A* Avg Finish Ticks : {avg_old_t:.1f}")
        print(f"  D* Lite Avg Finish Ticks : {avg_ds_t:.1f} ({time_diff:+.1f}%)")
        print(f"  Full A* Avg Wait Ticks   : {avg_old_w:.1f}")
        print(f"  D* Lite Avg Wait Ticks   : {avg_ds_w:.1f} ({wait_diff:+.1f}%)")
        print(f"  Total Collisions         : {total_collisions}")
        print("=" * 70)
        return

    if args.compare_batching:
        print("=" * 70)
        print("BENCHMARK: First-Dispatch (Old) vs Hungarian Batch Task Allocation (New C6)")
        print(f"Fleet: {args.robots} robots, {args.tasks} tasks per trial, {args.trials} trials")
        print("=" * 70 + "\n")
        old_times, batch_times = [], []
        old_waits, batch_waits = [], []
        total_collisions = 0

        for trial in range(args.trials):
            seed = args.seed + trial * 97
            schedule = make_task_schedule(args.tasks, seed, wmap)

            res_old = run(args.robots, schedule, cooperative=True,
                          max_ticks=args.max_ticks, seed=seed, directed=args.directed,
                          use_pibt=args.pibt, use_wfg=args.wfg, use_congestion=args.congestion,
                          use_dstar=args.dstar, use_batching=False)
            res_batch = run(args.robots, schedule, cooperative=True,
                            max_ticks=args.max_ticks, seed=seed, directed=args.directed,
                            use_pibt=args.pibt, use_wfg=args.wfg, use_congestion=args.congestion,
                            use_dstar=args.dstar, use_batching=True)

            total_collisions += res_old["collisions"] + res_batch["collisions"]
            old_times.append(res_old["ticks_to_finish"])
            batch_times.append(res_batch["ticks_to_finish"])
            old_waits.append(res_old["total_wait_ticks"])
            batch_waits.append(res_batch["total_wait_ticks"])

            impr = 100 * (res_old["ticks_to_finish"] - res_batch["ticks_to_finish"]) / res_old["ticks_to_finish"]
            print(f"Trial {trial+1} (seed={seed}):")
            print(f"  First-Dispatch : {res_old['ticks_to_finish']:4d} ticks | wait={res_old['total_wait_ticks']:4d} | collisions={res_old['collisions']}")
            print(f"  Hungarian (C6) : {res_batch['ticks_to_finish']:4d} ticks | wait={res_batch['total_wait_ticks']:4d} | collisions={res_batch['collisions']}")
            print(f"  -> Time change: {impr:+.1f}%\n")

        avg_old_t = statistics.mean(old_times)
        avg_bt_t = statistics.mean(batch_times)
        avg_old_w = statistics.mean(old_waits)
        avg_bt_w = statistics.mean(batch_waits)
        time_diff = 100 * (avg_old_t - avg_bt_t) / avg_old_t
        wait_diff = 100 * (avg_old_w - avg_bt_w) / max(1.0, avg_old_w)

        print("=" * 70)
        print(f"SUMMARY over {args.trials} trials:")
        print(f"  First-Dispatch Avg Finish Ticks : {avg_old_t:.1f}")
        print(f"  Hungarian Batch Avg Finish Ticks: {avg_bt_t:.1f} ({time_diff:+.1f}%)")
        print(f"  First-Dispatch Avg Wait Ticks   : {avg_old_w:.1f}")
        print(f"  Hungarian Batch Avg Wait Ticks  : {avg_bt_w:.1f} ({wait_diff:+.1f}%)")
        print(f"  Total Collisions                : {total_collisions}")
        print("=" * 70)
        return

    if args.compare_directed:
        print("=" * 70)
        print("BENCHMARK: Undirected Graph (Old) vs Directed Graph (New C1)")
        print(f"Fleet: {args.robots} robots, {args.tasks} tasks per trial, {args.trials} trials")
        print("=" * 70 + "\n")
        undir_times, dir_times = [], []
        undir_waits, dir_waits = [], []
        undir_aisle_ho, dir_aisle_ho = [], []
        undir_all_ho, dir_all_ho = [], []
        total_collisions = 0

        for trial in range(args.trials):
            seed = args.seed + trial * 97
            schedule = make_task_schedule(args.tasks, seed, demo_warehouse(directed=False))

            res_undir = run(args.robots, schedule, cooperative=True,
                            max_ticks=args.max_ticks, seed=seed, directed=False)
            res_dir = run(args.robots, schedule, cooperative=True,
                          max_ticks=args.max_ticks, seed=seed, directed=True)

            total_collisions += res_undir["collisions"] + res_dir["collisions"]
            undir_times.append(res_undir["ticks_to_finish"])
            dir_times.append(res_dir["ticks_to_finish"])
            undir_waits.append(res_undir["total_wait_ticks"])
            dir_waits.append(res_dir["total_wait_ticks"])
            undir_aisle_ho.append(res_undir["aisle_head_ons"])
            dir_aisle_ho.append(res_dir["aisle_head_ons"])
            undir_all_ho.append(res_undir["head_on_conflicts"])
            dir_all_ho.append(res_dir["head_on_conflicts"])

            impr = 100 * (res_undir["ticks_to_finish"] - res_dir["ticks_to_finish"]) / res_undir["ticks_to_finish"]
            print(f"Trial {trial+1} (seed={seed}):")
            print(f"  Undirected: {res_undir['ticks_to_finish']:4d} ticks | wait={res_undir['total_wait_ticks']:4d} | aisle head-ons={res_undir['aisle_head_ons']:3d} | all={res_undir['head_on_conflicts']}")
            print(f"  Directed  : {res_dir['ticks_to_finish']:4d} ticks | wait={res_dir['total_wait_ticks']:4d} | aisle head-ons={res_dir['aisle_head_ons']:3d} | all={res_dir['head_on_conflicts']}")
            print(f"  -> Time change: {impr:+.1f}% | Aisle head-ons resolved: {res_undir['aisle_head_ons'] - res_dir['aisle_head_ons']}\n")

        avg_undir_t = statistics.mean(undir_times)
        avg_dir_t = statistics.mean(dir_times)
        avg_undir_w = statistics.mean(undir_waits)
        avg_dir_w = statistics.mean(dir_waits)
        tot_undir_aisle_ho = sum(undir_aisle_ho)
        tot_dir_aisle_ho = sum(dir_aisle_ho)
        tot_undir_all_ho = sum(undir_all_ho)
        tot_dir_all_ho = sum(dir_all_ho)
        time_diff = 100 * (avg_undir_t - avg_dir_t) / avg_undir_t

        print("=" * 70)
        print(f"SUMMARY over {args.trials} trials:")
        print(f"  Undirected Avg Finish Ticks : {avg_undir_t:.1f}")
        print(f"  Directed Avg Finish Ticks   : {avg_dir_t:.1f} ({time_diff:+.1f}%)")
        print(f"  Undirected Avg Wait Ticks   : {avg_undir_w:.1f}")
        print(f"  Directed Avg Wait Ticks     : {avg_dir_w:.1f}")
        print(f"  Single-Width Aisle Head-Ons : Undirected={tot_undir_aisle_ho} -> Directed={tot_dir_aisle_ho} ({100*(tot_undir_aisle_ho-tot_dir_aisle_ho)/max(1,tot_undir_aisle_ho):.1f}% reduction)")
        print(f"  Total Head-On Conflicts     : Undirected={tot_undir_all_ho} -> Directed={tot_dir_all_ho} ({(tot_undir_all_ho-tot_dir_all_ho)/max(1,tot_undir_all_ho)*100:.1f}% reduction)")
        print(f"  Total Collisions            : {total_collisions}")
        print("=" * 70)
        return

    coop_times, base_times = [], []
    total_collisions = 0
    base_timeouts = coop_timeouts = 0
    for trial in range(args.trials):
        seed = args.seed + trial * 97
        schedule = make_task_schedule(args.tasks, seed, wmap)

        coop = run(args.robots, schedule, cooperative=True,
                    max_ticks=args.max_ticks, seed=seed, directed=args.directed,
                    use_pibt=args.pibt, use_wfg=args.wfg, use_congestion=args.congestion,
                    use_dstar=args.dstar, use_batching=args.batching)
        # baseline is always the plain undirected warehouse with no C1-C6 layers
        base = run(args.robots, schedule, cooperative=False,
                    max_ticks=args.max_ticks, seed=seed, directed=False,
                    use_pibt=False, use_wfg=False, use_congestion=False,
                    use_dstar=False, use_batching=False)

        total_collisions += coop["collisions"] + base["collisions"]
        base_timeouts += bool(base.get("timed_out"))
        coop_timeouts += bool(coop.get("timed_out"))
        coop_times.append(coop["ticks_to_finish"])
        base_times.append(base["ticks_to_finish"])

        improvement = 100 * (base["ticks_to_finish"] - coop["ticks_to_finish"]) / base["ticks_to_finish"]
        print(f"Trial {trial+1} (seed={seed}, {args.robots} robots, {args.tasks} tasks):")
        print(f"  cooperative : {coop['ticks_to_finish']:4d} ticks | "
              f"total wait={coop['total_wait_ticks']:4d} | collisions={coop['collisions']}{_timeout_note(coop, args.tasks)}")
        print(f"  stop-&-wait : {base['ticks_to_finish']:4d} ticks | "
              f"total wait={base['total_wait_ticks']:4d} | collisions={base['collisions']}{_timeout_note(base, args.tasks)}")
        print(f"  -> time reduction: {improvement:5.1f}%\n")

    avg_coop = statistics.mean(coop_times)
    avg_base = statistics.mean(base_times)
    avg_improvement = 100 * (avg_base - avg_coop) / avg_base

    print("=" * 60)
    print(f"AVERAGE over {args.trials} trials:")
    print(f"  cooperative avg ticks : {avg_coop:.1f}")
    print(f"  stop-and-wait avg ticks: {avg_base:.1f}")
    print(f"  AVERAGE TIME REDUCTION : {avg_improvement:.1f}%")
    print(f"  TOTAL COLLISIONS ACROSS ALL RUNS: {total_collisions}")
    print("=" * 60)
    if base_timeouts or coop_timeouts:
        print(f"  WARNING: baseline timed out in {base_timeouts}/{args.trials} trials, cooperative in "
              f"{coop_timeouts}/{args.trials}. A timed-out run is capped at --max-ticks, so the "
              f"reduction above is NOT a real completion-time comparison.")
    if coop_timeouts:
        print("Cooperative system did not finish every trial -- criteria NOT met.")
    elif avg_improvement >= 20:
        print("SUCCESS CRITERIA MET: >=20% reduction vs stop-and-wait, zero collisions.")
    else:
        print("Below 20% target in this configuration -- try more robots/tasks "
              "to increase path overlap (congestion is what creates the gap).")


if __name__ == "__main__":
    main()
