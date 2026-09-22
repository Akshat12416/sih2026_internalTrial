"""
core/pibt.py
============
L4 Multi-Agent Coordination Layer: Priority Inheritance with Backtracking (PIBT).
Reference:
  Okumura, K., Machida, M., Défago, X., & Tamura, S. (2019).
  "Priority Inheritance with Backtracking for Multi-Agent Path Finding."
  IJCAI 2019 / Artificial Intelligence Journal (AIJ 2022).

Replaces the slow multi-round negotiation (honk -> wait -> dynamic starvation -> replan)
with a deterministic, single-timestep coordination mechanism.

Key concepts:
  1. Priority Metric:
     P(i) = (goal_since, priority_base, robot_id)
     goal_since = tick the robot got its current goal. As in the PIBT paper, the
     robot that has gone longest without reaching its goal has top priority, so it
     always makes progress (no push-back-and-forth livelock), then drops back once
     it arrives. The key is CONSTANT until the goal changes, so two robots
     comparing each other's broadcast ranks one tick apart still agree.
     Closer distance to goal breaks ties efficiently.
  2. Recursive Push with Priority Inheritance:
     When a high-priority agent A desires cell C occupied by agent B, B temporarily
     inherits A's priority and tries to find a valid adjacent move.
  3. Backtracking:
     If B cannot find any valid move without collision, the push is undone,
     and A falls back to its next-best candidate or stays in place.
  4. Swap Collision Prevention:
     Blocker B is forbidden from moving into A's current cell.
  5. L2 Safety Shield Independence:
     L2 absolute-occupancy safety shield retains final veto authority over any move.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from core.planner import WarehouseMap, Cell, manhattan


@dataclass
class PIBTAgentState:
    robot_id: str
    pos: Cell
    goal: Optional[Cell]
    goal_since: int
    priority_base: int
    path: List[Cell]
    is_nudged: bool = False

    @property
    def priority_key(self) -> Tuple[int, int, str]:
        # Lower tuple value = Higher priority
        return (self.goal_since, self.priority_base, self.robot_id)


def get_candidate_moves(agent: PIBTAgentState, wmap: WarehouseMap, pusher_pos: Optional[Cell] = None) -> List[Cell]:
    """
    Returns candidate next cells for the agent, ordered from best to worst.
    Preferred move is path[1] (from A*), followed by other valid neighbors
    sorted by Manhattan distance to goal, and finally staying in place.
    """
    curr = agent.pos
    preferred = agent.path[1] if agent.path and len(agent.path) >= 2 else None
    if preferred == curr:
        preferred = None  # a stationary broadcast ([pos, pos, ...]) is not a move

    valid_neighbors = [n for n in wmap.neighbours(curr) if not wmap.is_blocked(n)]

    goal = agent.goal or curr
    aisle_cells = getattr(wmap, "aisle_cells", set())
    if preferred is None and pusher_pos is not None:
        # Pushed without a personal path: strongly prefer lateral/perpendicular steps
        # to clear the pusher's lane of travel instead of staying in front of them.
        p_dr, p_dc = curr[0] - pusher_pos[0], curr[1] - pusher_pos[1]
        def lateral_score(c: Cell) -> Tuple[int, int, int]:
            s_dr, s_dc = c[0] - curr[0], c[1] - curr[1]
            is_lateral = 0 if (s_dr * p_dr + s_dc * p_dc == 0) else 1
            in_aisle = 1 if c in aisle_cells else 0
            return (is_lateral, in_aisle, manhattan(c, goal))
        valid_neighbors.sort(key=lateral_score)
    elif preferred is None:
        valid_neighbors.sort(key=lambda c: (1 if c in aisle_cells else 0, manhattan(c, goal)))
    else:
        valid_neighbors.sort(key=lambda c: manhattan(c, goal))

    candidates: List[Cell] = []
    if preferred is None and (agent.goal is None or curr == agent.goal):
        # Idle or already at goal: stay put unless a higher-priority agent pushes us
        # or we have been nudged to make way.
        if not getattr(agent, "is_nudged", False):
            candidates.append(curr)
    if preferred and preferred in valid_neighbors:
        candidates.append(preferred)
        for n in valid_neighbors:
            if n != preferred:
                candidates.append(n)
    else:
        candidates.extend(valid_neighbors)

    # Staying in place is the safe fallback candidate
    if curr not in candidates:
        candidates.append(curr)

    return candidates


def run_pibt_step(agents: Dict[str, PIBTAgentState], wmap: WarehouseMap) -> Dict[str, Cell]:
    """
    Executes one timestep of PIBT across all agents.
    Returns: mapping of robot_id -> next_cell for this tick.
    """
    sorted_agents = sorted(agents.values(), key=lambda a: a.priority_key)
    occupied_now: Dict[Cell, PIBTAgentState] = {a.pos: a for a in agents.values()}
    reserved_next: Dict[Cell, str] = {}
    next_pos: Dict[str, Cell] = {}

    def pibt_func(agent: PIBTAgentState, forbidden_cells: Set[Cell], visited_chain: Set[str], pusher_pos: Optional[Cell] = None) -> bool:
        visited_chain.add(agent.robot_id)
        candidates = get_candidate_moves(agent, wmap, pusher_pos=pusher_pos)

        for cand in candidates:
            if cand in forbidden_cells:
                continue
            if cand in reserved_next:
                continue
            if wmap.is_blocked(cand):
                continue

            blocker = occupied_now.get(cand)
            if blocker and blocker.robot_id != agent.robot_id and blocker.robot_id in next_pos:
                # Occupant's move is already decided -- never re-push it.
                # It is vacating cand (cand not in reserved_next), so cand is free,
                # unless it is moving into our cell, which would be a swap collision.
                if next_pos[blocker.robot_id] == agent.pos:
                    continue
                blocker = None
            if blocker and blocker.robot_id != agent.robot_id:
                # Cand is occupied by another agent.
                # Avoid cycles in the push chain
                if blocker.robot_id in visited_chain:
                    continue

                # Temporarily reserve cand for this agent
                reserved_next[cand] = agent.robot_id
                next_pos[agent.robot_id] = cand

                # Push blocker with inherited priority.
                # Blocker cannot step into agent.pos (swap collision prevention).
                sub_forbidden = set(forbidden_cells) | {agent.pos}
                if pibt_func(blocker, sub_forbidden, visited_chain, pusher_pos=agent.pos):
                    return True
                else:
                    # Push failed: backtrack
                    del reserved_next[cand]
                    del next_pos[agent.robot_id]
                    continue
            else:
                # Cand is unoccupied or is agent's own current cell
                reserved_next[cand] = agent.robot_id
                next_pos[agent.robot_id] = cand
                return True

        # Fallback: try to stay in place if not reserved
        if agent.pos not in reserved_next and agent.pos not in forbidden_cells:
            reserved_next[agent.pos] = agent.robot_id
            next_pos[agent.robot_id] = agent.pos
            return True

        return False

    for agent in sorted_agents:
        if agent.robot_id not in next_pos:
            pibt_func(agent, forbidden_cells=set(), visited_chain=set())

    # Guarantee every agent has a defined move (stay in place if unassigned)
    for agent in agents.values():
        if agent.robot_id not in next_pos:
            next_pos[agent.robot_id] = agent.pos

    return next_pos
