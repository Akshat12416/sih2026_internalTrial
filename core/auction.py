"""
core/auction.py
===============
L6 Task Allocation Layer: Batch Assignment with Hungarian Algorithm (Decision C6).

Instead of greedy first-dispatch (where tasks are awarded individually the instant
they arrive), arriving tasks are pooled across a batch accumulation window.
The fleet solves a min-cost bipartite matching problem:
    min sum_{i, j} C[i, j] * x_{i, j}
yielding a globally optimal robot <-> task assignment without any central auctioneer.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import numpy as np
try:
    from scipy.optimize import linear_sum_assignment
except ImportError:
    linear_sum_assignment = None


def hungarian_batch_assign(
    open_bids: Dict[str, Dict[str, float]],
    ready_task_ids: List[str],
) -> Dict[str, str]:
    """Deterministically assigns ready tasks to bidding robots to minimize
    total fleet cost using the Hungarian algorithm (Kuhn-Munkres).

    Parameters:
      open_bids: task_id -> {robot_id: bid_cost}
      ready_task_ids: list of task_ids whose batch accumulation window has matured

    Returns:
      task_id -> winning_robot_id
    """
    if not ready_task_ids:
        return {}

    # Sort deterministically so all peer AMRs construct identical matrices
    tasks = sorted(ready_task_ids)
    all_robots = sorted(list(set(
        rid for tid in tasks for rid in open_bids.get(tid, {}).keys()
    )))

    if not all_robots:
        return {}

    # If only 1 task or 1 robot, fall back to simple min bid
    if len(tasks) == 1 or len(all_robots) == 1:
        assignments: Dict[str, str] = {}
        for tid in tasks:
            bids = open_bids.get(tid, {})
            if bids:
                winner = min(bids.items(), key=lambda kv: (kv[1], kv[0]))[0]
                assignments[tid] = winner
        return assignments

    # Build cost matrix: rows = robots, cols = tasks
    INF_PENALTY = 100000.0
    num_robots = len(all_robots)
    num_tasks = len(tasks)

    # Square or rectangular matrix: linear_sum_assignment handles rectangular (M x N)
    cost_matrix = np.full((num_robots, num_tasks), INF_PENALTY, dtype=float)

    for j, tid in enumerate(tasks):
        bids = open_bids.get(tid, {})
        for i, rid in enumerate(all_robots):
            if rid in bids:
                cost_matrix[i, j] = float(bids[rid])

    if linear_sum_assignment is not None:
        row_ind, col_ind = linear_sum_assignment(cost_matrix)
    else:
        # Pure Python fallback for greedy matching if scipy missing
        row_ind, col_ind = _greedy_matching(cost_matrix)

    assignments: Dict[str, str] = {}
    for r_idx, c_idx in zip(row_ind, col_ind):
        if cost_matrix[r_idx, c_idx] < INF_PENALTY:
            tid = tasks[c_idx]
            rid = all_robots[r_idx]
            assignments[tid] = rid

    # Unmatched tasks (more tasks than robots) stay open and are re-matched next
    # tick -- handing them to an already-matched robot would break one-task-per-robot.
    return assignments


def _greedy_matching(cost_matrix: np.ndarray) -> Tuple[List[int], List[int]]:
    """Greedy fallback matching."""
    rows, cols = cost_matrix.shape
    used_rows = set()
    used_cols = set()
    row_ind, col_ind = [], []

    # Flatten entries
    entries = []
    for r in range(rows):
        for c in range(cols):
            entries.append((cost_matrix[r, c], r, c))
    entries.sort(key=lambda x: x[0])

    for cost, r, c in entries:
        if r not in used_rows and c not in used_cols:
            used_rows.add(r)
            used_cols.add(c)
            row_ind.append(r)
            col_ind.append(c)

    return row_ind, col_ind
