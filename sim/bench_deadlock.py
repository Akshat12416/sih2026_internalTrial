"""
sim/bench_deadlock.py
=====================
Benchmarks L3 Deadlock Detection: Old Starvation Timeout vs Wait-For Graph (C3).

Creates an intentional circular deadlock scenario:
  4 robots arranged in a cycle at an intersection:
    R1 at (4, 4) wanting (4, 5)
    R2 at (4, 5) wanting (5, 5)
    R3 at (5, 5) wanting (5, 4)
    R4 at (5, 4) wanting (4, 4)

Measures:
  - Deadlock detection & recovery latency (ticks & seconds at 4Hz / 0.25s per tick)
  - Total wait ticks accumulated across the fleet until deadlock is broken.
"""
from __future__ import annotations
import time
from typing import Dict, List, Tuple

from core.layouts import demo_warehouse
from core.planner import Cell
from core.robot_agent import RobotAgent, Task
from core import config
from sim.fast_sim import Bus

TICK_DURATION_S = 0.25


def run_cycle_deadlock(use_wfg: bool, max_ticks: int = 50) -> Dict:
    wmap = demo_warehouse(directed=False)
    bus = Bus()
    
    # 4 robots in a ring cycle
    ring = [
        ("R1", (4, 4), (4, 8), [(4, 4), (4, 5), (4, 6), (4, 7), (4, 8)], 0),
        ("R2", (4, 5), (8, 5), [(4, 5), (5, 5), (6, 5), (7, 5), (8, 5)], 1),
        ("R3", (5, 5), (5, 1), [(5, 5), (5, 4), (5, 3), (5, 2), (5, 1)], 2),
        ("R4", (5, 4), (0, 4), [(5, 4), (4, 4), (3, 4), (2, 4), (1, 4), (0, 4)], 3),
    ]

    agents: Dict[str, RobotAgent] = {}
    for rid, start, goal, init_path, prio in ring:
        a = RobotAgent(
            robot_id=rid,
            pos=start,
            wmap=wmap,
            send=lambda m, rid=rid: bus.send(rid, m),
            priority_base=prio,
            cooperative=True,
        )
        a.current_task = Task(f"T_{rid}", start, goal)
        a.state = "EN_ROUTE_TO_DROPOFF"
        a.path = list(init_path)
        a.t = 1  # the ring is already formed and announced: skip the startup hello tick
        agents[rid] = a
        bus.register(rid, a.on_message)

    deadlock_broken_tick = None
    deadlock_victim = None

    for tick in range(1, max_ticks + 1):
        # Broadcast intent
        for a in agents.values():
            horizon = [a.pos] + a.path[1:6] if len(a.path) >= 2 else [a.pos] * 6
            a.send({"type": "intent", "robot_id": a.robot_id, "priority": a.priority_base, "path": horizon, "start_t": tick})

        # Step agents -- with USE_WAITFOR_GRAPH each robot checks its OWN local
        # wait-for graph inside step() and yields only if it is the victim
        config.USE_WAITFOR_GRAPH = use_wfg
        try:
            for a in agents.values():
                a.step()
        finally:
            config.USE_WAITFOR_GRAPH = False
        # Deadlock is broken the first tick a robot yields (blacklists its contested
        # cell) -- via WFG victim selection or via the old starvation timer
        if deadlock_broken_tick is None:
            for a in agents.values():
                if a.avoid_until:
                    deadlock_broken_tick = tick
                    deadlock_victim = a.robot_id
                    break

        # Check if at least one robot successfully moved
        any_moved = any(a.pos != start for a, (rid, start, _, _, _) in zip(agents.values(), ring))
        if any_moved and deadlock_broken_tick is not None:
            return {
                "recovery_ticks": deadlock_broken_tick,
                "recovery_seconds": deadlock_broken_tick * TICK_DURATION_S,
                "victim": deadlock_victim,
                "total_wait_ticks": sum(a.total_wait_ticks for a in agents.values()),
            }

    return {
        "recovery_ticks": max_ticks,
        "recovery_seconds": max_ticks * TICK_DURATION_S,
        "victim": deadlock_victim,
        "total_wait_ticks": sum(a.total_wait_ticks for a in agents.values()),
        "timed_out": True,
    }


def main():
    print("=" * 70)
    print("BENCHMARK: L3 Deadlock Detection — Starvation Timeout vs WFG (C3)")
    print("Scenario: 4 Robots in a Mutual Wait Cycle (R1->R2->R3->R4->R1)")
    print("=" * 70 + "\n")

    res_old = run_cycle_deadlock(use_wfg=False)
    res_wfg = run_cycle_deadlock(use_wfg=True)

    print(f"Old Timeout Deadlock Recovery:")
    print(f"  Recovery latency : {res_old['recovery_ticks']} ticks ({res_old['recovery_seconds']:.2f}s)")
    print(f"  Total fleet wait : {res_old['total_wait_ticks']} ticks")
    print(f"  Victim chosen    : {res_old['victim']}\n")

    print(f"Wait-For Graph (WFG) Deadlock Recovery:")
    print(f"  Recovery latency : {res_wfg['recovery_ticks']} ticks ({res_wfg['recovery_seconds']:.2f}s)")
    print(f"  Total fleet wait : {res_wfg['total_wait_ticks']} ticks")
    print(f"  Victim chosen    : {res_wfg['victim']}\n")

    speedup = 100 * (res_old['recovery_ticks'] - res_wfg['recovery_ticks']) / res_old['recovery_ticks']
    wait_drop = 100 * (res_old['total_wait_ticks'] - res_wfg['total_wait_ticks']) / max(1, res_old['total_wait_ticks'])
    print("=" * 70)
    print(f"SUMMARY: Deadlock recovery time dropped by {speedup:.1f}% ({res_old['recovery_seconds']:.2f}s -> {res_wfg['recovery_seconds']:.2f}s)!")
    print(f"Fleet wait ticks reduced by {wait_drop:.1f}% ({res_old['total_wait_ticks']} -> {res_wfg['total_wait_ticks']} ticks).")
    print("=" * 70)


if __name__ == "__main__":
    main()
