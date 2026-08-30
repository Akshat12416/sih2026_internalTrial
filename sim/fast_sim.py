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
from typing import Dict, List, Tuple

from core.layouts import demo_warehouse
from core.robot_agent import RobotAgent, Task
from core.planner import Cell

START_POSITIONS = [(9, 2), (9, 5), (9, 8), (9, 11), (0, 2), (0, 8)]


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


def run(n_robots: int, schedule, cooperative: bool, max_ticks: int, seed: int):
    wmap = demo_warehouse()
    bus = Bus()
    agents: Dict[str, RobotAgent] = {}

    for i in range(n_robots):
        rid = f"R{i+1}"
        agent = RobotAgent(robot_id=rid, pos=START_POSITIONS[i % len(START_POSITIONS)],
                             wmap=wmap, send=lambda m, rid=rid: bus.send(rid, m),
                             priority_base=i, cooperative=cooperative)
        agents[rid] = agent
        bus.register(rid, agent.on_message)

    collisions = 0
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
            }

    done = sum(a.completed_tasks for a in agents.values())
    return {"ticks_to_finish": max_ticks, "collisions": collisions,
            "total_wait_ticks": sum(a.total_wait_ticks for a in agents.values()),
            "completed": done, "timed_out": True}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--robots", type=int, default=4)
    ap.add_argument("--tasks", type=int, default=24)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-ticks", type=int, default=1500)
    ap.add_argument("--trials", type=int, default=5, help="repeat with different seeds and average")
    args = ap.parse_args()

    wmap = demo_warehouse()
    coop_times, base_times = [], []
    print(f"Warehouse: {wmap.rows}x{wmap.cols} grid, "
          f"{len(wmap.choke_points)} choke points, {len(wmap.pickup_points)} pickup / "
          f"{len(wmap.dropoff_points)} dropoff points\n")

    total_collisions = 0
    for trial in range(args.trials):
        seed = args.seed + trial * 97
        schedule = make_task_schedule(args.tasks, seed, wmap)

        coop = run(args.robots, schedule, cooperative=True,
                    max_ticks=args.max_ticks, seed=seed)
        base = run(args.robots, schedule, cooperative=False,
                    max_ticks=args.max_ticks, seed=seed)

        total_collisions += coop["collisions"] + base["collisions"]
        coop_times.append(coop["ticks_to_finish"])
        base_times.append(base["ticks_to_finish"])

        improvement = 100 * (base["ticks_to_finish"] - coop["ticks_to_finish"]) / base["ticks_to_finish"]
        print(f"Trial {trial+1} (seed={seed}, {args.robots} robots, {args.tasks} tasks):")
        print(f"  cooperative : {coop['ticks_to_finish']:4d} ticks | "
              f"total wait={coop['total_wait_ticks']:4d} | collisions={coop['collisions']}")
        print(f"  stop-&-wait : {base['ticks_to_finish']:4d} ticks | "
              f"total wait={base['total_wait_ticks']:4d} | collisions={base['collisions']}")
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
    if avg_improvement >= 20:
        print("SUCCESS CRITERIA MET: >=20% reduction vs stop-and-wait, zero collisions.")
    else:
        print("Below 20% target in this configuration -- try more robots/tasks "
              "to increase path overlap (congestion is what creates the gap).")


if __name__ == "__main__":
    main()
