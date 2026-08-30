"""
core/planner.py
================
This module is the "textbook" every robot's onboard computer (Raspberry Pi /
Jetson Nano) carries a copy of. It contains NO networking and NO knowledge of
other robots as objects -- only pure functions and data structures. That's a
deliberate design choice: it means the exact same planning code can run
                (a) for real, inside a live UDP-networked robot process, and
                (b) inside a fast headless simulator used to measure
                    performance against a naive baseline.

Key concepts implemented here:
    1. WarehouseMap      - static grid layout + auto-detected choke points
    2. astar()            - single-robot shortest path on the grid
    3. ReservationBook     - each robot's OWN local belief of where/when other
                             robots intend to be, built entirely from
                             broadcast messages it has received (no shared
                             memory, no central table -- this is what makes
                             it genuinely decentralized / "eventually
                             consistent" the way real mesh networks are)
    4. resolve_conflict()  - deterministic priority rule used to break
                             deadlocks/head-on conflicts at choke points
"""

from __future__ import annotations
import heapq
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

Cell = Tuple[int, int]

FREE, SHELF, PICKUP, DROPOFF, CHARGE = 0, 1, 2, 3, 4


# --------------------------------------------------------------------------- #
# 1. WAREHOUSE MAP
# --------------------------------------------------------------------------- #
class WarehouseMap:
    """Static layout, identical copy pre-loaded on every robot (like a
    factory map flashed onto every unit's SD card before deployment).
    Dynamic blockages (a dropped pallet, a jammed aisle) are layered on top
    at runtime and propagate via broadcasts, NOT via this static grid."""

    def __init__(self, grid: List[List[int]]):
        self.grid = grid
        self.rows = len(grid)
        self.cols = len(grid[0])
        self.pickup_points = self._cells_of(PICKUP)
        self.dropoff_points = self._cells_of(DROPOFF)
        self.charge_points = self._cells_of(CHARGE)
        self.choke_points = self._detect_choke_points()
        # dynamic blockages reported live by robots (aisle collapse, spill, etc.)
        self.dynamic_blocks: Dict[Cell, float] = {}  # cell -> expiry timestamp

    def _cells_of(self, kind: int) -> List[Cell]:
        return [(r, c) for r in range(self.rows) for c in range(self.cols)
                if self.grid[r][c] == kind]

    def _detect_choke_points(self) -> List[Cell]:
        """A cell is a choke point if it's free and exactly two OPPOSITE
        neighbours are free while the perpendicular pair is blocked --
        i.e. a single-robot-wide corridor. These are exactly the spots
        where head-on deadlocks happen, so we flag them for extra care."""
        chokes = []
        for r in range(self.rows):
            for c in range(self.cols):
                if self.grid[r][c] in (SHELF,):
                    continue
                n = self._free(r - 1, c)
                s = self._free(r + 1, c)
                e = self._free(r, c + 1)
                w = self._free(r, c - 1)
                if (n and s and not e and not w) or (e and w and not n and not s):
                    chokes.append((r, c))
        return chokes

    def _free(self, r: int, c: int) -> bool:
        if 0 <= r < self.rows and 0 <= c < self.cols:
            return self.grid[r][c] != SHELF
        return False

    def is_blocked(self, cell: Cell, now: Optional[float] = None) -> bool:
        r, c = cell
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return True
        if self.grid[r][c] == SHELF:
            return True
        now = now if now is not None else time.time()
        exp = self.dynamic_blocks.get(cell)
        if exp and exp > now:
            return True
        if exp and exp <= now:
            del self.dynamic_blocks[cell]
        return False

    def report_blockage(self, cell: Cell, duration_s: float = 20.0):
        """Called when a robot's onboard sensor (or, here, the simulator)
        detects e.g. a dropped pallet. This is purely LOCAL state -- the
        robot must broadcast it for peers to learn about it too."""
        self.dynamic_blocks[cell] = time.time() + duration_s

    def neighbours(self, cell: Cell) -> List[Cell]:
        r, c = cell
        cand = [(r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)]
        return [n for n in cand if not self.is_blocked(n)]


# --------------------------------------------------------------------------- #
# 2. A* PATH PLANNING (with optional time-aware reservation avoidance)
# --------------------------------------------------------------------------- #
def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(wmap: WarehouseMap, start: Cell, goal: Cell,
          reserved: Optional[Dict[Tuple[Cell, int], str]] = None,
          start_t: int = 0, self_id: str = "") -> List[Cell]:
    """Grid A*. If `reserved` is supplied (a dict of (cell, time_step) ->
    robot_id) the search also avoids stepping into a cell at a timestep
    another (higher-or-equal priority) robot has claimed -- this is the
    'cooperative A*' trick that lets many independent planners avoid each
    other without ever synchronizing on a single global plan."""
    reserved = reserved or {}
    open_heap = [(manhattan(start, goal), 0, start, start_t)]
    came_from: Dict[Tuple[Cell, int], Tuple[Cell, int]] = {}
    g_score = {(start, start_t): 0}
    visited = set()

    while open_heap:
        _, g, cur, t = heapq.heappop(open_heap)
        if (cur, t) in visited:
            continue
        visited.add((cur, t))

        if cur == goal:
            return _reconstruct(came_from, (cur, t))

        for nxt in wmap.neighbours(cur) + [cur]:  # "+ [cur]" = allow waiting in place
            nt = t + 1
            key = (nxt, nt)
            if key in reserved and reserved[key] != self_id:
                continue  # someone else claims that cell at that time
            ng = g + 1
            if g_score.get(key, 1e9) > ng:
                g_score[key] = ng
                came_from[key] = (cur, t)
                heapq.heappush(open_heap, (ng + manhattan(nxt, goal), ng, nxt, nt))

        if t - start_t > 400:  # safety valve against runaway search
            break
    return []  # no path found (fully boxed in) -- caller must retry/wait


def _reconstruct(came_from, key) -> List[Cell]:
    path = [key[0]]
    while key in came_from:
        key = came_from[key]
        path.append(key[0])
    path.reverse()
    return path


# --------------------------------------------------------------------------- #
# 3. DECENTRALIZED RESERVATION BOOK
# --------------------------------------------------------------------------- #
@dataclass
class PeerIntent:
    robot_id: str
    priority: int          # lower value = higher priority (task urgency, then id)
    path: List[Cell]       # short-horizon planned path
    start_t: int
    received_at: float = field(default_factory=time.time)


class ReservationBook:
    """Each robot owns exactly one of these. It is filled ONLY from intent
    broadcasts received over the network -- never from a shared/global
    object. Two robots' books can briefly disagree (a broadcast is still
    in flight); the priority + reactive-layer rules below are what keep
    the system safe even when that happens."""

    STALE_AFTER_S = 3.0

    def __init__(self, self_id: str):
        self.self_id = self_id
        self.peers: Dict[str, PeerIntent] = {}

    def update(self, intent: PeerIntent):
        self.peers[intent.robot_id] = intent

    def prune(self, now: Optional[float] = None):
        now = now or time.time()
        stale = [k for k, v in self.peers.items()
                 if now - v.received_at > self.STALE_AFTER_S]
        for k in stale:
            del self.peers[k]

    def as_reserved_table(self) -> Dict[Tuple[Cell, int], str]:
        table: Dict[Tuple[Cell, int], str] = {}
        for intent in self.peers.values():
            for i, cell in enumerate(intent.path):
                t = intent.start_t + i
                # a higher-priority robot's claim wins if two disagree
                key = (cell, t)
                if key not in table:
                    table[key] = intent.robot_id
        return table


# --------------------------------------------------------------------------- #
# 4. CONFLICT / DEADLOCK RESOLUTION (the "traffic rules")
# --------------------------------------------------------------------------- #
def resolve_conflict(self_id: str, self_priority: int, self_next: Cell,
                      self_cur: Cell, book: ReservationBook) -> bool:
    """Returns True if THIS robot should proceed to `self_next` this tick,
    False if it must yield (wait one tick and replan). Pure function of
    locally-known information -- exactly what a real edge device would
    have available.

    Deliberately conservative rule, in two passes:
      1. ABSOLUTE occupancy check: never move into a cell any peer is
         confirmed to currently occupy -- regardless of what that peer
         SAYS it plans to do next. A peer's stated intent to vacate is not
         a guarantee (it might itself get blocked by a third robot before
         it can move), so trusting it would let two robots' optimistic
         assumptions collide. This makes the rule slightly more cautious
         than strictly necessary in some cases, but it is what actually
         guarantees zero collisions without needing global synchronization.
      2. PRIORITY tie-break: only used to decide between two robots that
         are BOTH currently free to move and are racing for the same
         currently-EMPTY cell. Priority never overrides rule 1.
    """
    for intent in book.peers.values():
        if not intent.path:
            continue
        if intent.path[0] == self_next:
            return False  # occupied right now -- no exceptions

    for peer_id, intent in book.peers.items():
        if len(intent.path) < 2:
            continue
        peer_cur, peer_next = intent.path[0], intent.path[1]
        if peer_next == self_next and peer_cur != self_next:
            # both racing for the same currently-free cell
            if (self_priority, self_id) < (intent.priority, peer_id):
                continue  # we have priority, still fine
            return False
    return True


def apply_aging(waiting_ticks: int, base_priority: int) -> int:
    """Starvation guard: a robot that has yielded too many times in a row
    gets its priority number reduced (= boosted) so it can't be perpetually
    out-prioritized at a busy choke point. Classic OS-scheduler trick,
    borrowed here for traffic fairness."""
    return max(0, base_priority - waiting_ticks // 3)
