"""
sim/bench_matrix.py
===================
Comprehensive Multi-Robot Fleet Benchmark Harness (Session 7 / Final Evaluation).

Evaluates the Baseline (Naive Stop-and-Wait) vs Full Autonomous Layered Stack
(C1 Directed Graph + C2 PIBT + C3 WFG + C4 Congestion + C5 D* Lite + C6 Batching + L1 Perception)
across a matrix of fleet sizes (default 3, 5, 10 AMRs) over seeded runs. Each fleet
runs on a warehouse scaled to its size (core.layouts.layout_for_fleet).

Reports:
  - Completion Time (ticks): Mean, Median, Standard Deviation
  - Total Fleet Wait Ticks: Mean and % Reduction
  - Fleet Throughput (tasks/tick): Mean and % Gain
  - Collisions: Total count (strictly 0)
  - Head-on Deadlocks: Aisle vs Corridor counts
"""

from __future__ import annotations
import argparse
import statistics
import time
from typing import Dict, List, Tuple

from core.layouts import build_warehouse, layout_for_fleet
from core import config
from sim.fast_sim import run, make_task_schedule


def run_benchmark_matrix(fleet_sizes: List[int], num_runs: int = 10, tasks_per_robot: int = 6):
    print("=" * 85)
    print("       DECENTRALIZED AMR FLEET ARCHITECTURE - COMPREHENSIVE BENCHMARK MATRIX")
    print(f"       Fleet Sizes: {fleet_sizes} | Runs per Size: {num_runs} | Tasks per Robot: {tasks_per_robot}")
    print("       Baseline: Stop-and-Wait | Full System: C1 + C2 + C3 + C4 + C5 + C6 + L1")
    print("=" * 85 + "\n")

    summary_rows = []

    for n_robots in fleet_sizes:
        n_tasks = n_robots * tasks_per_robot
        layout = layout_for_fleet(n_robots)  # warehouse grows with the fleet
        probe = build_warehouse(*layout)
        free = sum(not probe.is_blocked((r, c)) for r in range(probe.rows) for c in range(probe.cols))
        print(f">>> Running Fleet Size = {n_robots} AMRs ({n_tasks} Tasks, {num_runs} Seeded Trials) "
              f"on {probe.rows}x{probe.cols} warehouse ({free} free cells, {free // n_robots}/robot)...")

        base_times: List[int] = []
        full_times: List[int] = []
        base_waits: List[int] = []
        full_waits: List[int] = []
        base_head_ons: List[int] = []
        full_head_ons: List[int] = []
        total_collisions_base = 0
        total_collisions_full = 0
        base_done: List[int] = []
        full_done: List[int] = []
        base_timeouts = full_timeouts = 0

        for trial in range(num_runs):
            seed = 1000 + trial * 37 + n_robots * 13
            wmap = build_warehouse(*layout, directed=False)
            schedule = make_task_schedule(n_tasks, seed, wmap)

            # 1. Baseline (Stop-and-Wait, undirected, no C1-C6)
            res_base = run(
                n_robots=n_robots,
                schedule=schedule,
                cooperative=False,
                max_ticks=2000,
                seed=seed,
                directed=False,
                use_pibt=False,
                use_wfg=False,
                use_congestion=False,
                use_dstar=False,
                use_batching=False,
                layout=layout,
            )

            # 2. Full System (All layers active)
            res_full = run(
                n_robots=n_robots,
                schedule=schedule,
                cooperative=True,
                max_ticks=2000,
                seed=seed,
                directed=True,
                use_pibt=True,
                use_wfg=True,
                use_congestion=True,
                use_dstar=True,
                use_batching=True,
                layout=layout,
            )

            base_times.append(res_base["ticks_to_finish"])
            full_times.append(res_full["ticks_to_finish"])
            base_waits.append(res_base["total_wait_ticks"])
            full_waits.append(res_full["total_wait_ticks"])
            base_head_ons.append(res_base["head_on_conflicts"])
            full_head_ons.append(res_full["head_on_conflicts"])
            total_collisions_base += res_base["collisions"]
            total_collisions_full += res_full["collisions"]
            base_done.append(res_base["completed"])
            full_done.append(res_full["completed"])
            base_timeouts += bool(res_base.get("timed_out"))
            full_timeouts += bool(res_full.get("timed_out"))

        # Statistics computation
        base_mean_t = statistics.mean(base_times)
        base_med_t = statistics.median(base_times)
        base_std_t = statistics.stdev(base_times) if len(base_times) > 1 else 0.0

        full_mean_t = statistics.mean(full_times)
        full_med_t = statistics.median(full_times)
        full_std_t = statistics.stdev(full_times) if len(full_times) > 1 else 0.0

        time_reduction = 100.0 * (base_mean_t - full_mean_t) / base_mean_t
        wait_reduction = 100.0 * (statistics.mean(base_waits) - statistics.mean(full_waits)) / max(1.0, statistics.mean(base_waits))

        # throughput = tasks actually COMPLETED per tick (a timed-out run did not finish n_tasks)
        base_th = statistics.mean(d / t for d, t in zip(base_done, base_times))
        full_th = statistics.mean(d / t for d, t in zip(full_done, full_times))
        th_gain = 100.0 * (full_th - base_th) / base_th if base_th else float("inf")

        row = {
            "robots": n_robots,
            "tasks": n_tasks,
            "base_mean": base_mean_t,
            "base_med": base_med_t,
            "base_std": base_std_t,
            "full_mean": full_mean_t,
            "full_med": full_med_t,
            "full_std": full_std_t,
            "time_reduction": time_reduction,
            "wait_reduction": wait_reduction,
            "base_th": base_th,
            "full_th": full_th,
            "th_gain": th_gain,
            "base_ho": sum(base_head_ons),
            "full_ho": sum(full_head_ons),
            "base_coll": total_collisions_base,
            "full_coll": total_collisions_full,
            "base_to": base_timeouts,
            "full_to": full_timeouts,
        }
        summary_rows.append(row)

        print(f"  -> Baseline: {base_mean_t:.1f} \u00b1 {base_std_t:.1f} ticks | Wait={statistics.mean(base_waits):.1f} | Collisions={total_collisions_base}")
        print(f"  -> Full Sys: {full_mean_t:.1f} \u00b1 {full_std_t:.1f} ticks | Wait={statistics.mean(full_waits):.1f} | Collisions={total_collisions_full}")
        print(f"  -> Timed out (2000 ticks): Baseline {base_timeouts}/{num_runs} "
              f"(avg {statistics.mean(base_done):.1f}/{n_tasks} tasks done) | Full Sys {full_timeouts}/{num_runs}")
        print(f"  -> Speedup: {time_reduction:+.1f}% | Throughput: {base_th:.4f} -> {full_th:.4f} tasks/tick\n")

    # Print Final Markdown Results Table
    print("\n" + "=" * 105)
    print("                                  FINAL BENCHMARK MATRIX REPORT")
    print("=" * 105)
    print("| Fleet Size | Tasks | Baseline Mean (s/t) | Full System Mean (s/t) | Fleet Speedup | Wait Reduction | Throughput t/tick (B->F) | Baseline Coll | Full System Coll | Timeouts B/F |")
    print("|:----------:|:-----:|:-------------------:|:----------------------:|:-------------:|:--------------:|:------------------------:|:-------------:|:----------------:|:------------:|")
    for r in summary_rows:
        print(
            f"| {r['robots']:10d} | {r['tasks']:5d} | {r['base_mean']:6.1f} \u00b1 {r['base_std']:4.1f} t  | "
            f"{r['full_mean']:6.1f} \u00b1 {r['full_std']:4.1f} t   | {r['time_reduction']:+11.1f}% | "
            f"{r['wait_reduction']:12.1f}% | {r['base_th']:.3f} -> {r['full_th']:.3f} | {r['base_coll']:13d} | {r['full_coll']:16d} | {r['base_to']:5d}/{r['full_to']:<6d} |"
        )
    print("=" * 105)
    if any(r["base_to"] for r in summary_rows):
        print("NOTE: timed-out runs are capped at 2000 ticks, so 'Fleet Speedup' is a lower bound, not a measured ratio.")
    return summary_rows


def main():
    parser = argparse.ArgumentParser(description="Multi-Robot Fleet Benchmark Matrix")
    parser.add_argument("--runs", type=int, default=10, help="Number of seeded trials per fleet size (default: 10)")
    parser.add_argument("--sizes", nargs="+", type=int, default=[3, 5, 10], help="Fleet sizes to evaluate")
    args = parser.parse_args()

    run_benchmark_matrix(fleet_sizes=args.sizes, num_runs=args.runs)


if __name__ == "__main__":
    main()
