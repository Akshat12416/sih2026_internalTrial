"""
sim/scenarios.py
================
The story.md cases as runnable data: every case is a set of real start/goal
cells on the demo map plus the feature flags that make the case visible.

This is the single source of truth for three consumers:
  - docs/story_cases/make_diagrams.py  (the static figures)
  - dashboard/server.py /api/cases     (the click-to-run case picker)
  - the CLI below                      (python -m sim.scenarios --list)

`run_case()` runs the scenario headlessly through the exact same
`RobotAgent.step()` the live robots use, and records one frame per tick so the
dashboard can replay it on its own grid.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core import config
from core.layouts import demo_warehouse
from core.planner import Cell, astar
from core.robot_agent import RobotAgent, Task
from sim.fast_sim import Bus

TICK_S = 0.25          # 4 Hz, the nominal edge-board tick
BLOCK_FOREVER = 1e6    # dynamic blockage that never expires during a case

# Flag presets. "legacy" = the Part 1 negotiation stack, "full" = C1-C6.
LEGACY = dict(directed=False, pibt=False, wfg=False, congestion=False, dstar=False)
FULL = dict(directed=True, pibt=True, wfg=True, congestion=True, dstar=False)


@dataclass
class Case:
    id: str
    title: str
    part: str                       # "1" (negotiation era) or "2" (layered architecture)
    layer: str                      # e.g. "L6 auction", "L4 PIBT"
    figure: str                     # figure png that contains this case
    robots: List[Tuple[str, Cell, Optional[Cell], int]]   # id, start, goal, priority_base
    note: str                       # what goes wrong
    fix: str                        # what we changed
    modes: Dict[str, dict] = field(default_factory=lambda: {"after": dict(FULL)})
    blocks: List[Cell] = field(default_factory=list)
    max_ticks: int = 120

    def public(self) -> dict:
        """What the dashboard needs to mark the points before anything runs."""
        return {
            "id": self.id, "title": self.title, "part": self.part, "layer": self.layer,
            "figure": self.figure, "note": self.note, "fix": self.fix,
            "modes": list(self.modes),
            "blocks": [list(b) for b in self.blocks],
            "robots": [{"id": rid, "start": list(s), "goal": list(g) if g else None,
                        "priority": p} for rid, s, g, p in self.robots],
        }


# --------------------------------------------------------------------------- #
# The cases. Every cell here is a real free cell on the 11x15 demo map.
# --------------------------------------------------------------------------- #
CASES: List[Case] = [
    Case(
        id="case1", title="Dropoff must be part of the bid", part="1", layer="L6 auction",
        figure="fig1_dispatch.png",
        robots=[("R1", (0, 4), (0, 5), 0), ("R2", (9, 4), (0, 5), 1)],
        note="Task pickup P(0,5) -> dropoff D(10,2). R1 is 1 step from the pickup but on the "
             "wrong side of the map for the dropoff; R2 is further from the pickup and already "
             "on the dropoff side. Bidding on pickup distance alone sends R1 across the floor twice.",
        fix="bid = path(start -> pickup) + path(pickup -> dropoff), so the best whole trip wins.",
    ),
    Case(
        id="case2", title="Absolute occupancy (never enter an occupied cell)", part="1",
        layer="L2 safety shield", figure="fig2_collision.png",
        robots=[("R1", (8, 7), (0, 7), 0), ("R2", (6, 7), None, 1)],
        note="R2 sits in aisle col 7 and broadcasts 'I leave next tick'. If R1 pre-enters (6,7) "
             "on that promise and R2 is delayed, they occupy the same cell.",
        fix="Rule 1: a peer's confirmed cell is never entered, whatever its intent claims.",
    ),
    Case(
        id="case3", title="Space-time reservation (cooperative A*)", part="1",
        layer="L5 routing", figure="fig2_collision.png",
        robots=[("R1", (4, 1), (4, 13), 0), ("R2", (0, 7), (8, 7), 1)],
        note="Both routes cross cell (4,7). Planning blind, they only react when they physically "
             "meet, so they stop-and-go through the intersection.",
        fix="6-tick intent broadcasts fill each peer's ReservationBook; A* skips (cell, t) pairs "
            "already claimed, so they weave.",
    ),
    Case(
        id="case4", title="Honk paralysis / premature detour", part="1", layer="L4 negotiation",
        figure="fig3_standoff.png",
        robots=[("R5", (8, 4), (0, 4), 0), ("R3", (5, 4), None, 4)],
        note="IDLE R3 blocks aisle col 4. R5 nudges it every single tick, which restarts R3's "
             "escape plan each time - both freeze, then R5 gives up and takes a huge detour.",
        fix="Wait limit raised to 10 ticks, and a nudged robot enters MAKING WAY: it plans a full "
            "escape path and ignores all further honks until it is clear.",
    ),
    Case(
        id="case5", title="Quadratic battery penalty", part="1", layer="L6 auction",
        figure="fig1_dispatch.png",
        robots=[("R3", (9, 8), (10, 8), 0), ("R5", (8, 13), (10, 8), 1)],
        note="Task pickup sits next to R3 (70% battery). R5 is across the floor at 95%. A linear "
             "battery term let R5 outbid on charge alone and drive the whole map.",
        fix="Above 60% battery the penalty is 0 - healthy robots compete purely on distance. "
            "Below 60% it grows quadratically so low robots stop taking work.",
    ),
    Case(
        id="case6", title="Symmetric livelock (head-on, both busy)", part="1",
        layer="L4 negotiation", figure="fig3_standoff.png",
        robots=[("R2", (4, 1), (4, 13), 0), ("R4", (4, 13), (4, 1), 1)],
        note="Two EN_ROUTE robots meet head-on with the same 10-tick limit: they time out on the "
             "same tick, mirror each other into the next aisle, and meet again. Forever.",
        fix="Dynamic limit 10+(5-priority)*4 (18-26 ticks) breaks the symmetry, and a blacklisted "
            "cell is blocked for 400 ticks so A* is forced into a real spatial detour.",
        max_ticks=160,
    ),
    Case(
        id="case7", title="Predictive bidding + auction-window discount", part="1",
        layer="L6 auction", figure="fig1_dispatch.png",
        robots=[("R4", (4, 4), (10, 8), 0), ("R6", (8, 1), (10, 10), 1)],
        note="R4 is EN_ROUTE to dropoff D(10,8) and a new task appears at pickup (10,10), two "
             "cells away. Busy robots were barred from bidding, so distant idle R6 won it. "
             "Worse: a busy robot keeps driving during the 3-tick auction, so its bid is stale-high.",
        fix="Busy robots bid predictively (ticks_left + dropoff->pickup) minus the 3-tick auction "
            "window, and queue the win - they chain straight into it on dropoff.",
    ),
    Case(
        id="case10", title="Goal yielding at a blocked pickup", part="1", layer="L3 recovery",
        figure="fig3_standoff.png",
        robots=[("R3", (0, 5), (10, 2), 0), ("R1", (0, 4), (0, 5), 1), ("R5", (0, 7), (0, 5), 2)],
        note="Loaded R3 stands on pickup P(0,5) in the 1-wide row 0; R1 and R5 both want that "
             "exact cell. A robot could never blacklist its own goal, so all three reset their "
             "timers forever and nobody backs out.",
        fix="A goal may now be blacklisted. When the path then fails, the robot parks at the "
            "nearest free staging cell, lets the aisle drain, and tries again.",
        max_ticks=160,
    ),
    Case(
        id="case11", title="C1 - directed one-way aisles", part="2", layer="L5 graph",
        figure="fig4_c1_c2.png",
        robots=[("R1", (8, 7), (0, 7), 0), ("R2", (0, 7), (8, 7), 1)],
        note="Two robots enter the same single-width aisle (col 7) from opposite ends. Every Part 1 "
             "mechanism fires - nudge, wait, starvation, blacklist, detour - and it still costs "
             "seconds, over and over, all day.",
        fix="Make single-width aisles one-way, alternating: col 4 N, col 7 S, col 10 N. Corridors "
            "stay two-way. A head-on inside an aisle becomes unrepresentable. Measured on this "
            "case: 49 -> 15 ticks; fleet-wide, single-width head-ons 532 -> 0.",
        modes={"before": dict(LEGACY), "after": dict(LEGACY, directed=True)},
    ),
    Case(
        id="case12a", title="C2 - PIBT on a 2-robot head-on", part="2", layer="L4 coordination",
        figure="fig4_c1_c2.png",
        robots=[("R1", (4, 1), (4, 7), 0), ("R2", (4, 7), (4, 1), 1)],
        note="Head-on in the row-4 corridor. The negotiation protocol needs several message "
             "rounds to converge, and each round costs a tick.",
        fix="PIBT: one deterministic priority-inheritance step per tick, no rounds, no timers. "
            "Measured on this case: 47 -> 15 ticks, delay vs free-flow 41 -> 9, wait 55 -> 0.",
        modes={"before": dict(LEGACY), "after": dict(LEGACY, pibt=True)},
    ),
    Case(
        id="case12b", title="C2 - PIBT on a 3-robot crossing", part="2", layer="L4 coordination",
        figure="fig4_c1_c2.png",
        robots=[("R1", (1, 7), (7, 7), 0), ("R2", (4, 4), (4, 10), 1), ("R3", (7, 7), (1, 7), 2)],
        note="Three robots contend for intersection (4,7). Negotiation cost grows with the number "
             "of robots involved - exactly when you can least afford it.",
        fix="rank = (goal_since, priority_base, robot_id) is constant until the goal changes, so "
            "peers comparing broadcasts one tick apart still agree. Measured on this case: "
            "45 -> 15 ticks, delay 39 -> 9.",
        modes={"before": dict(LEGACY), "after": dict(LEGACY, pibt=True)},
    ),
    Case(
        id="case13", title="C3 - 4-robot ring deadlock", part="2", layer="L3 deadlock",
        figure="fig5_c3_c4.png",
        robots=[("R1", (8, 4), (8, 8), 0), ("R2", (8, 5), (10, 5), 1),
                ("R3", (9, 5), (9, 1), 2), ("R4", (9, 4), (4, 4), 3)],
        note="Each robot wants the cell the next one is standing on: a perfect 4-cycle. No local "
             "rule can see it, so the only answer was to burn the 18-26 tick starvation timer.",
        fix="Each robot builds a wait-for graph from its own intents and runs 3-colour DFS, and "
            "the victim is picked deterministically so exactly one yields. Honest attribution on "
            "THIS ring: 32 -> 9 ticks, but PIBT does the work - WFG alone measures 33 ticks. WFG "
            "earns its place on rings PIBT cannot rotate out of, not on this one.",
        modes={"before": dict(LEGACY), "after": dict(LEGACY, wfg=True, pibt=True)},
        max_ticks=60,
    ),
    Case(
        id="case14", title="C4 - congestion-aware routing", part="2", layer="L5 routing",
        figure="fig5_c3_c4.png",
        robots=[("R1", (10, 2), (0, 5), 0), ("R2", (10, 3), (0, 8), 1),
                ("R3", (10, 4), (0, 11), 2), ("R4", (10, 5), (0, 2), 3)],
        note="Four robots leave the staging row for four different top bays. A* is optimal, "
             "deterministic and blind to peers, so they all funnel into the same nearest aisle "
             "and queue nose-to-tail while the other aisles sit empty.",
        fix="Peer intents build a decaying traffic heatmap; A* step cost becomes 1 + alpha*congestion, "
            "so a slightly longer empty aisle beats a shorter crowded one. Measured on this "
            "case: 54 -> 19 ticks, delay 37 -> 2.",
        modes={"before": dict(LEGACY), "after": dict(LEGACY, congestion=True)},
    ),
    Case(
        id="case15", title="C5 - D* Lite replan around a dropped pallet", part="2",
        layer="L5 replanning", figure="fig6_c5_c6_l1.png",
        robots=[("R1", (8, 4), (0, 4), 0)], blocks=[(2, 4)],
        note="A pallet blocks (2,4) after the robot has committed to the aisle. Full A* re-expands "
             "the whole grid for one changed cell - wasteful on a Pi 4 / Jetson Nano.",
        fix="D* Lite repairs only the inconsistent vertices (~17 nodes). Honest result: 13% faster "
            "on the directed graph, actually SLOWER undirected on a map this small.",
        modes={"before": dict(LEGACY), "after": dict(LEGACY, directed=True, dstar=True)},
    ),
    Case(
        id="case17", title="L1 - perception sees what the map does not", part="2",
        layer="L1 perception", figure="fig6_c5_c6_l1.png",
        robots=[("R1", (8, 7), (0, 7), 0)], blocks=[(5, 7)],
        note="An unmapped obstacle sits in aisle col 7. The first integration scanned the robot's "
             "own map instead of physical ground truth, so L1 never fired once - and nothing "
             "crashed, so it looked like it worked.",
        fix="Perception scans sensor_truth (the world, not our belief). A confirmed detection is "
            "treated like a peer alert: mark the map, replan, broadcast.",
    ),
    Case(
        id="case19", title="Decentralized L2 race: two robots, one empty cell", part="2",
        layer="L2 safety shield", figure="fig7_decentral.png",
        robots=[("R1", (4, 6), (4, 8), 0), ("R2", (8, 7), (0, 7), 1)],
        note="Both intend to enter the SAME EMPTY cell (4,7) on the same tick over an "
             "unsynchronised radio. Neither occupies it, so absolute occupancy says nothing.",
        fix="Symmetric rule: yield if a peer with a better broadcast rank intends the same empty "
            "cell - so exactly one enters. Plus a hello tick before any robot's first move. "
            "Watch the collision counter, not the clock: this case is about 0 vs >0.",
        modes={"after": dict(LEGACY, pibt=True)},
    ),
]

BY_ID = {c.id: c for c in CASES}


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run_case(case_id: str, mode: str = "after") -> dict:
    """Run one case headlessly and return per-tick frames + metrics.

    Robots run the same RobotAgent.step() the live UDP processes run; there is
    no coordinator here either.
    """
    case = BY_ID[case_id]
    flags = case.modes.get(mode) or next(iter(case.modes.values()))
    saved = {k: getattr(config, k) for k in
             ("USE_PIBT", "USE_WAITFOR_GRAPH", "USE_CONGESTION_COST", "USE_DSTAR_LITE")}
    config.USE_PIBT = flags.get("pibt", False)
    config.USE_WAITFOR_GRAPH = flags.get("wfg", False)
    config.USE_CONGESTION_COST = flags.get("congestion", False)
    config.USE_DSTAR_LITE = flags.get("dstar", False)
    try:
        return _run_case(case, flags, mode if mode in case.modes else next(iter(case.modes)))
    finally:
        for k, v in saved.items():
            setattr(config, k, v)


def _run_case(case: Case, flags: dict, mode: str) -> dict:
    wmap = demo_warehouse(directed=flags.get("directed", False))
    for cell in case.blocks:
        wmap.report_blockage(cell, BLOCK_FOREVER)

    bus = Bus()
    agents: Dict[str, RobotAgent] = {}
    goals: Dict[str, Optional[Cell]] = {}
    for rid, start, goal, prio in case.robots:
        a = RobotAgent(robot_id=rid, pos=start, wmap=wmap,
                       send=lambda m, rid=rid: bus.send(rid, m),
                       priority_base=prio, cooperative=True)
        if goal is not None:
            a.current_task = Task(task_id=f"T_{rid}", pickup=start, dropoff=goal)
            a.state = "EN_ROUTE_TO_DROPOFF"
        agents[rid] = a
        goals[rid] = goal
        bus.register(rid, a.on_message)

    active = [rid for rid, g in goals.items() if g is not None]
    # free-flow = the slowest robot's trip with nobody else on the floor
    free_flow = max((len(astar(wmap, agents[r].pos, goals[r]) or [0]) - 1) for r in active) if active else 0

    frames, collisions, done_tick = [], 0, None
    reached = set()
    for tick in range(1, case.max_ticks + 1):
        if tick == 1:   # hello tick: announce before anyone moves
            for a in agents.values():
                a._replan()
                horizon = [a.pos] + a.path[1:6] if len(a.path) >= 2 else [a.pos] * 6
                a.send({"type": "intent", "robot_id": a.robot_id,
                        "priority": a.priority_base, "path": horizon, "start_t": tick})

        for a in agents.values():
            a.step()

        occupied: Dict[Cell, str] = {}
        for a in agents.values():
            if a.pos in occupied:
                collisions += 1
            occupied[a.pos] = a.robot_id

        frames.append({"t": tick, "robots": [
            {"id": rid, "r": a.pos[0], "c": a.pos[1], "state": a.state,
             "wait": a.total_wait_ticks,
             "intent": [list(p) for p in a.path[1:6]]} for rid, a in agents.items()]})

        for rid in active:
            if agents[rid].pos == goals[rid] or agents[rid].completed_tasks >= 1:
                reached.add(rid)
        if len(reached) == len(active):
            done_tick = tick
            break

    ticks = done_tick or case.max_ticks
    return {
        "case": case.public(),
        "mode": mode,
        "frames": frames,
        "metrics": {
            "ticks": ticks,
            "seconds": round(ticks * TICK_S, 2),
            "free_flow_ticks": free_flow,
            "delay_ticks": ticks - free_flow,
            "wait_ticks": sum(a.total_wait_ticks for a in agents.values()),
            "collisions": collisions,
            "finished": done_tick is not None,
        },
    }


def main():
    ap = argparse.ArgumentParser(description="Run a story.md case headlessly.")
    ap.add_argument("--list", action="store_true", help="list every case id")
    ap.add_argument("--case", help="case id to run, e.g. case12a")
    ap.add_argument("--mode", default="after", help="before | after")
    args = ap.parse_args()

    if args.list or not args.case:
        for c in CASES:
            print(f"{c.id:10s} part{c.part}  {c.layer:18s} {c.title}  [{'/'.join(c.modes)}]")
        return
    res = run_case(args.case, args.mode)
    m = res["metrics"]
    print(f"{args.case} [{args.mode}]: {m['ticks']} ticks ({m['seconds']}s), "
          f"free-flow {m['free_flow_ticks']}, delay {m['delay_ticks']}, "
          f"wait {m['wait_ticks']}, collisions {m['collisions']}, "
          f"finished={m['finished']}")


if __name__ == "__main__":
    main()
