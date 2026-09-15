"""
sim/bench_dstar.py
==================
Benchmark comparing Full A* replanning vs D* Lite incremental replanning
upon dynamic blockage events (Decision C5).

Measures:
  - Replan computation time per blocked-aisle / dynamic obstacle event (microseconds)
  - Number of graph node expansions
  - Resulting path optimality
"""

import time
import random
from typing import List, Tuple
from core.layouts import demo_warehouse
from core.planner import astar, Cell
from core.dstar_lite import DStarLite


def run_benchmark(num_trials: int = 100, directed: bool = True):
    print("=" * 70)
    mode_str = "Directed Graph" if directed else "Undirected Graph"
    print(f"  BENCHMARK: Full A* vs D* Lite Incremental Replanning ({mode_str})")
    print(f"  Trials: {num_trials} blockage events across random start-goal pairs")
    print("=" * 70)

    wmap = demo_warehouse(directed=directed)

    # Valid non-shelf locations
    free_cells: List[Cell] = []
    for r in range(wmap.rows):
        for c in range(wmap.cols):
            if not wmap.is_blocked((r, c)):
                free_cells.append((r, c))

    astar_times_us: List[float] = []
    dstar_times_us: List[float] = []
    dstar_expansions_list: List[int] = []
    path_len_diffs: List[int] = []

    successful_events = 0

    rng = random.Random(42)

    for trial in range(num_trials):
        start = rng.choice(free_cells)
        goal = rng.choice(free_cells)
        if start == goal:
            continue

        # Initial path
        init_path = astar(wmap, start, goal)
        if not init_path or len(init_path) < 4:
            continue

        # Choose a cell along the route to suddenly block
        block_idx = rng.randint(1, len(init_path) - 2)
        block_cell = init_path[block_idx]

        # Robot has progressed to step right before block_cell
        robot_pos = init_path[block_idx - 1]

        # --- Benchmark D* Lite ---
        # 1. Initialize router at start
        dstar = DStarLite(wmap, start, goal)
        dstar.compute_shortest_path()
        # 2. Advance to robot_pos
        dstar.move_to(robot_pos)
        # 3. Dynamic blockage event occurs
        t0 = time.perf_counter_ns()
        dstar.update_blockage(block_cell, True)
        dstar_exp = dstar.compute_shortest_path()
        dstar_path = dstar.extract_path()
        t1 = time.perf_counter_ns()
        dstar_duration_us = (t1 - t0) / 1000.0

        # --- Benchmark Full A* ---
        wmap.report_blockage(block_cell, duration_s=60.0)
        t2 = time.perf_counter_ns()
        astar_path = astar(wmap, robot_pos, goal)
        t3 = time.perf_counter_ns()
        astar_duration_us = (t3 - t2) / 1000.0
        # Clear blockage from wmap for next run
        wmap.dynamic_blocks.clear()

        # Compare results
        if dstar_path and astar_path:
            astar_times_us.append(astar_duration_us)
            dstar_times_us.append(dstar_duration_us)
            dstar_expansions_list.append(dstar_exp)
            path_len_diffs.append(abs(len(dstar_path) - len(astar_path)))
            successful_events += 1

    if not successful_events:
        print("No valid test cases generated.")
        return

    avg_astar_us = sum(astar_times_us) / len(astar_times_us)
    avg_dstar_us = sum(dstar_times_us) / len(dstar_times_us)
    avg_exp = sum(dstar_expansions_list) / len(dstar_expansions_list)
    speedup = ((avg_astar_us - avg_dstar_us) / avg_astar_us) * 100.0

    print(f"\nCompleted {successful_events} dynamic obstacle / aisle-block events:")
    print(f"  - Full A* Mean Replan Latency:     {avg_astar_us:.2f} \u03bcs ({avg_astar_us/1000.0:.3f} ms)")
    print(f"  - D* Lite Mean Replan Latency:     {avg_dstar_us:.2f} \u03bcs ({avg_dstar_us/1000.0:.3f} ms)")
    print(f"  - Replan Latency Reduction:        {speedup:.1f}% faster")
    print(f"  - D* Lite Mean Node Expansions:    {avg_exp:.1f} nodes")
    print(f"  - Path Length Agreement:           {100.0 * (1 - sum(path_len_diffs)/len(path_len_diffs)):.1f}% identical")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark(num_trials=100, directed=False)
    print()
    run_benchmark(num_trials=100, directed=True)
