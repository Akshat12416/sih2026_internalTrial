"""
sim/bench_conflicts.py
======================
Benchmarks L4 Coordination: Old Multi-Round Negotiation vs New PIBT (Decision C2).

Measures conflict resolution time (ticks and equivalent seconds at 4Hz / 0.25s per tick):
  1. 2-robot head-on standoff scenario
  2. 3-robot crossing intersection scenario
  3. Full warehouse fleet comparison (Old Negotiation vs PIBT)
"""
from __future__ import annotations
import statistics
import time
from typing import Dict, List, Tuple

from core.layouts import demo_warehouse
from core.planner import Cell, astar
from core.robot_agent import RobotAgent, Task
from core import config
from sim.fast_sim import Bus, make_task_schedule


TICK_DURATION_S = 0.25  # Nominal 4 Hz tick rate on embedded edge device (Pi / Jetson)


def run_scenario(agents_setup: List[Tuple[str, Cell, Cell, int]], use_pibt: bool, max_ticks: int = 150) -> Dict:
    """
    Runs a precise multi-robot conflict scenario.
    agents_setup: list of (robot_id, start_pos, goal_pos, priority_base)
    Returns: ticks_to_clear, wait_ticks, collisions
    """
    wmap = demo_warehouse(directed=False)  # Undirected to allow head-on/crossing conflict test
    bus = Bus()
    agents: Dict[str, RobotAgent] = {}

    for rid, start_pos, goal, prio in agents_setup:
        agent = RobotAgent(
            robot_id=rid,
            pos=start_pos,
            wmap=wmap,
            send=lambda m, rid=rid: bus.send(rid, m),
            priority_base=prio,
            cooperative=True,
        )
        task = Task(task_id=f"T_{rid}", pickup=start_pos, dropoff=goal)
        agent.current_task = task
        agent.state = "EN_ROUTE_TO_DROPOFF"
        agents[rid] = agent
        bus.register(rid, agent.on_message)

    collisions = 0
    first_conflict_tick = None
    last_conflict_tick = None
    reached_goals = set()
    targets = {rid: goal for rid, _, goal, _ in agents_setup}
    # free-flow trip = slowest robot's shortest path with nobody else around
    free_flow = max(len(astar(wmap, start, goal)) - 1 for _, start, goal, _ in agents_setup)

    for tick in range(1, max_ticks + 1):
        if tick == 1:
            for a in agents.values():
                a._replan()
                horizon = [a.pos] + a.path[1:6] if len(a.path) >= 2 else [a.pos] * 6
                a.send({"type": "intent", "robot_id": a.robot_id, "priority": a.priority_base, "path": horizon, "start_t": tick})

        # Detect if agents are contending
        positions = {a.pos for a in agents.values()}
        is_contending = False
        for a in agents.values():
            if a.path and len(a.path) >= 2 and a.path[1] in positions:
                is_contending = True
                break

        if is_contending:
            first_conflict_tick = first_conflict_tick or tick
            last_conflict_tick = tick

        config.USE_PIBT = use_pibt  # each robot runs PIBT locally inside step()
        try:
            for a in agents.values():
                a.step()
        finally:
            config.USE_PIBT = False

        # Check collision
        occupied = {}
        for a in agents.values():
            if a.pos in occupied:
                collisions += 1
            occupied[a.pos] = a.robot_id

        for rid, a in agents.items():
            if a.pos == targets[rid] or a.completed_tasks >= 1:
                reached_goals.add(rid)

        if len(reached_goals) == len(agents_setup):
            # conflict window = first to last tick any robot's next cell was occupied (0 = never contended)
            conflict_res_time = (last_conflict_tick - first_conflict_tick + 1) if first_conflict_tick else 0
            return {
                "total_ticks": tick,
                "delay_ticks": tick - free_flow,
                "total_seconds": tick * TICK_DURATION_S,
                "conflict_ticks": conflict_res_time,
                "conflict_seconds": conflict_res_time * TICK_DURATION_S,
                "wait_ticks": sum(a.total_wait_ticks for a in agents.values()),
                "collisions": collisions,
            }

    conflict_res_time = max_ticks  # never resolved
    return {
        "total_ticks": max_ticks,
        "delay_ticks": max_ticks - free_flow,
        "total_seconds": max_ticks * TICK_DURATION_S,
        "conflict_ticks": conflict_res_time,
        "conflict_seconds": conflict_res_time * TICK_DURATION_S,
        "wait_ticks": sum(a.total_wait_ticks for a in agents.values()),
        "collisions": collisions,
        "timed_out": True,
    }


def benchmark_2robot_headon():
    print("=" * 70)
    print("SCENARIO 1: 2-Robot Head-On Conflict on the Row-4 Cross-Corridor")
    print("R1: (4, 1) -> (4, 7) | R2: (4, 7) -> (4, 1)")
    print("=" * 70)

    setup = [
        ("R1", (4, 1), (4, 7), 1),
        ("R2", (4, 7), (4, 1), 2),
    ]

    res_old = run_scenario(setup, use_pibt=False)
    res_pibt = run_scenario(setup, use_pibt=True)

    print(f"  Old Negotiation: conflict resolution = {res_old['conflict_ticks']} ticks ({res_old['conflict_seconds']:.2f}s) | total trip = {res_old['total_ticks']} ticks ({res_old['total_seconds']:.2f}s) | delay vs free-flow = {res_old['delay_ticks']} ticks | wait = {res_old['wait_ticks']} ticks")
    print(f"  PIBT (New L4)  : conflict resolution = {res_pibt['conflict_ticks']} ticks ({res_pibt['conflict_seconds']:.2f}s) | total trip = {res_pibt['total_ticks']} ticks ({res_pibt['total_seconds']:.2f}s) | delay vs free-flow = {res_pibt['delay_ticks']} ticks | wait = {res_pibt['wait_ticks']} ticks")
    speedup = 100 * (res_old['conflict_ticks'] - res_pibt['conflict_ticks']) / max(1, res_old['conflict_ticks'])
    print(f"  -> Conflict Resolution Latency Reduction: {speedup:.1f}% (from {res_old['conflict_seconds']:.2f}s down to {res_pibt['conflict_seconds']:.2f}s)!\n")
    return res_old, res_pibt


def benchmark_3robot_crossing():
    print("=" * 70)
    print("SCENARIO 2: 3-Robot Crossing Conflict at Intersection (4, 7)")
    print("R1: (1, 7) -> (7, 7) (North to South)")
    print("R2: (4, 4) -> (4, 10) (West to East)")
    print("R3: (7, 7) -> (1, 7) (South to North)")
    print("=" * 70)

    setup = [
        ("R1", (1, 7), (7, 7), 1),
        ("R2", (4, 4), (4, 10), 2),
        ("R3", (7, 7), (1, 7), 3),
    ]

    res_old = run_scenario(setup, use_pibt=False)
    res_pibt = run_scenario(setup, use_pibt=True)

    print(f"  Old Negotiation: conflict resolution = {res_old['conflict_ticks']} ticks ({res_old['conflict_seconds']:.2f}s) | total trip = {res_old['total_ticks']} ticks ({res_old['total_seconds']:.2f}s) | delay vs free-flow = {res_old['delay_ticks']} ticks | wait = {res_old['wait_ticks']} ticks")
    print(f"  PIBT (New L4)  : conflict resolution = {res_pibt['conflict_ticks']} ticks ({res_pibt['conflict_seconds']:.2f}s) | total trip = {res_pibt['total_ticks']} ticks ({res_pibt['total_seconds']:.2f}s) | delay vs free-flow = {res_pibt['delay_ticks']} ticks | wait = {res_pibt['wait_ticks']} ticks")
    speedup = 100 * (res_old['conflict_ticks'] - res_pibt['conflict_ticks']) / max(1, res_old['conflict_ticks'])
    print(f"  -> Conflict Resolution Latency Reduction: {speedup:.1f}% (from {res_old['conflict_seconds']:.2f}s down to {res_pibt['conflict_seconds']:.2f}s)!\n")
    return res_old, res_pibt


def main():
    res2_old, res2_pibt = benchmark_2robot_headon()
    res3_old, res3_pibt = benchmark_3robot_crossing()

    print("=" * 70)
    print("SUMMARY OF BENCHMARK RESULTS (Decision C2: PIBT vs Negotiation)")
    print("=" * 70)
    print("2-Robot Head-On Encounter:")
    print(f"  Old Negotiation : {res2_old['conflict_ticks']} ticks ({res2_old['conflict_seconds']:.2f}s) | Total trip: {res2_old['total_ticks']} ticks | Delay: {res2_old['delay_ticks']} ticks | Wait: {res2_old['wait_ticks']} ticks")
    print(f"  PIBT (L4)       : {res2_pibt['conflict_ticks']} ticks ({res2_pibt['conflict_seconds']:.2f}s) | Total trip: {res2_pibt['total_ticks']} ticks | Delay: {res2_pibt['delay_ticks']} ticks | Wait: {res2_pibt['wait_ticks']} ticks")
    print("3-Robot Crossing Intersection:")
    print(f"  Old Negotiation : {res3_old['conflict_ticks']} ticks ({res3_old['conflict_seconds']:.2f}s) | Total trip: {res3_old['total_ticks']} ticks | Delay: {res3_old['delay_ticks']} ticks | Wait: {res3_old['wait_ticks']} ticks")
    print(f"  PIBT (L4)       : {res3_pibt['conflict_ticks']} ticks ({res3_pibt['conflict_seconds']:.2f}s) | Total trip: {res3_pibt['total_ticks']} ticks | Delay: {res3_pibt['delay_ticks']} ticks | Wait: {res3_pibt['wait_ticks']} ticks")
    print("=" * 70)


if __name__ == "__main__":
    main()
