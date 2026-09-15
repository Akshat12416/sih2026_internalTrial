"""
core/dstar_lite.py
==================
Incremental heuristic replanner implementing Koenig & Likhachev's D* Lite
(optimized version). Part of L5 Global Routing Layer (Decision C5).

Instead of rerunning full A* from scratch when a dynamic blockage occurs (dropped pallet,
aisle jam), D* Lite reuses previous search trees and repairs only the inconsistent
states (rhs(s) != g(s)) via localized graph relaxation.
"""

from __future__ import annotations
import heapq
from typing import Dict, List, Optional, Set, Tuple
from core.planner import WarehouseMap, Cell

INF = float("inf")


class PriorityQueue:
    """Fast indexed min-priority queue for D* Lite supporting fast key updates."""

    __slots__ = ("_heap", "_keys")

    def __init__(self):
        self._heap: List[Tuple[float, float, Cell]] = []
        self._keys: Dict[Cell, Tuple[float, float]] = {}

    def insert(self, s: Cell, key: Tuple[float, float]):
        self._keys[s] = key
        heapq.heappush(self._heap, (key[0], key[1], s))

    def update(self, s: Cell, key: Tuple[float, float]):
        self._keys[s] = key
        heapq.heappush(self._heap, (key[0], key[1], s))

    def remove(self, s: Cell):
        self._keys.pop(s, None)

    def top_key(self) -> Tuple[float, float]:
        while self._heap:
            k1, k2, s = self._heap[0]
            if self._keys.get(s) == (k1, k2):
                return (k1, k2)
            heapq.heappop(self._heap)
        return (INF, INF)

    def pop(self) -> Tuple[Cell, Tuple[float, float]]:
        while self._heap:
            k1, k2, s = self._heap[0]
            heapq.heappop(self._heap)
            if self._keys.get(s) == (k1, k2):
                del self._keys[s]
                return s, (k1, k2)
        raise IndexError("pop from empty priority queue")

    def __contains__(self, s: Cell) -> bool:
        return s in self._keys

    def __len__(self) -> int:
        return len(self._keys)


class DStarLite:
    """Incremental replanner for single-agent navigation on a WarehouseMap.
    Search direction: backwards from s_goal to s_start.
    """

    def __init__(self, wmap: WarehouseMap, start: Cell, goal: Cell):
        self.wmap = wmap
        self.s_start = start
        self.s_goal = goal
        self.s_last = start
        self.k_m: float = 0.0

        self.g: Dict[Cell, float] = {}
        self.rhs: Dict[Cell, float] = {}
        self.U = PriorityQueue()
        self.nodes_expanded: int = 0

        # Precompute static graph topology for high performance
        self._succs_static: Dict[Cell, List[Cell]] = {}
        self._preds_static: Dict[Cell, List[Cell]] = {}
        self._build_static_topology()

        # Known blocked states monitored by this router
        self.blocked_cells: Set[Cell] = set()
        self._init_search()

    def _build_static_topology(self):
        for r in range(self.wmap.rows):
            for c in range(self.wmap.cols):
                cell = (r, c)
                if not self.wmap.is_blocked(cell):
                    succs = self.wmap.neighbours(cell)
                    self._succs_static[cell] = succs
                    for s in succs:
                        self._preds_static.setdefault(s, []).append(cell)

    def _calculate_key(self, s: Cell) -> Tuple[float, float]:
        g_val = self.g.get(s, INF)
        rhs_val = self.rhs.get(s, INF)
        val = g_val if g_val < rhs_val else rhs_val
        h = abs(self.s_start[0] - s[0]) + abs(self.s_start[1] - s[1])
        return (val + h + self.k_m, val)

    def _successors(self, s: Cell) -> List[Cell]:
        if s in self.blocked_cells or self.wmap.is_blocked(s):
            return []
        return [n for n in self._succs_static.get(s, [])
                if n not in self.blocked_cells and not self.wmap.is_blocked(n)]

    def _predecessors(self, s: Cell) -> List[Cell]:
        if s in self.blocked_cells or self.wmap.is_blocked(s):
            return []
        return [p for p in self._preds_static.get(s, [])
                if p not in self.blocked_cells and not self.wmap.is_blocked(p)]

    def _init_search(self):
        self.g.clear()
        self.rhs.clear()
        self.U = PriorityQueue()
        self.k_m = 0.0
        self.nodes_expanded = 0

        self.rhs[self.s_goal] = 0.0
        self.U.insert(self.s_goal, self._calculate_key(self.s_goal))

    def _update_vertex(self, u: Cell):
        if u != self.s_goal:
            succs = self._successors(u)
            if succs:
                best = INF
                for s_prime in succs:
                    cost = 1.0 + self.g.get(s_prime, INF)
                    if cost < best:
                        best = cost
                self.rhs[u] = best
            else:
                self.rhs[u] = INF

        self.U.remove(u)
        g_u = self.g.get(u, INF)
        rhs_u = self.rhs.get(u, INF)
        if g_u != rhs_u:
            self.U.insert(u, self._calculate_key(u))

    def compute_shortest_path(self, max_expansions: int = 2000) -> int:
        """Expands inconsistent vertices until s_start is consistent."""
        expansions = 0
        while expansions < max_expansions:
            top_key = self.U.top_key()
            start_key = self._calculate_key(self.s_start)
            g_start = self.g.get(self.s_start, INF)
            rhs_start = self.rhs.get(self.s_start, INF)

            if top_key >= start_key and rhs_start == g_start:
                break
            if len(self.U) == 0:
                break

            u, k_old = self.U.pop()
            k_new = self._calculate_key(u)
            expansions += 1
            self.nodes_expanded += 1

            if k_old < k_new:
                self.U.insert(u, k_new)
                continue

            g_u = self.g.get(u, INF)
            rhs_u = self.rhs.get(u, INF)

            if g_u > rhs_u:
                self.g[u] = rhs_u
                for p in self._predecessors(u):
                    self._update_vertex(p)
            else:
                self.g[u] = INF
                for p in self._predecessors(u):
                    self._update_vertex(p)
                self._update_vertex(u)

        return expansions

    def update_blockage(self, cell: Cell, is_blocked: bool):
        """Called when a dynamic obstacle appears or disappears."""
        was_blocked = cell in self.blocked_cells
        if was_blocked == is_blocked:
            return

        if is_blocked:
            self.blocked_cells.add(cell)
        else:
            self.blocked_cells.discard(cell)

        # Update affected predecessors and the cell itself
        for p in self._preds_static.get(cell, []):
            self._update_vertex(p)
        self._update_vertex(cell)

    def move_to(self, new_pos: Cell):
        """Updates robot position and modifies heuristic key modifier k_m."""
        if new_pos != self.s_start:
            self.k_m += abs(self.s_last[0] - new_pos[0]) + abs(self.s_last[1] - new_pos[1])
            self.s_last = new_pos
            self.s_start = new_pos

    def extract_path(self, max_len: int = 150) -> List[Cell]:
        """Extracts greedy path from current s_start to s_goal."""
        g_start = self.g.get(self.s_start, INF)
        rhs_start = self.rhs.get(self.s_start, INF)
        if g_start == INF and rhs_start == INF:
            return []

        path = [self.s_start]
        curr = self.s_start
        visited = {curr}

        while curr != self.s_goal and len(path) < max_len:
            succs = self._successors(curr)
            if not succs:
                return []

            best_succ = None
            best_cost = INF
            for s_prime in succs:
                cost = 1.0 + self.g.get(s_prime, INF)
                if cost < best_cost:
                    best_cost = cost
                    best_succ = s_prime

            if best_succ is None or best_cost >= INF or best_succ in visited:
                return []

            curr = best_succ
            visited.add(curr)
            path.append(curr)

        return path if curr == self.s_goal else []
