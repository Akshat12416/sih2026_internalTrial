"""Regression checks for the 2026-09-16 audit fixes. Run: python -m core.test_layers"""
from core.layouts import demo_warehouse
from core.pibt import PIBTAgentState, run_pibt_step
from core.robot_agent import RobotAgent, Task
from core.auction import hungarian_batch_assign
from sim.fast_sim import start_positions

# L1: a physical obstacle the map doesn't know about gets detected, reported and avoided
w = demo_warehouse()
sent = []
a = RobotAgent("R1", (4, 0), w, send=sent.append, sensor_truth={(4, 5)})
a.current_task = Task("t", (4, 0), (4, 10))
a.state = "EN_ROUTE_TO_DROPOFF"
for _ in range(20):
    a.step()
assert any(m["type"] == "blockage" and tuple(m["cell"]) == (4, 5) for m in sent), "perception never reported"
assert a.pos != (4, 4) or a.path, "robot stuck in front of detected obstacle"

# L4: idle / at-goal agents stay put, but can still be pushed aside
w = demo_warehouse()
idle = {"R1": PIBTAgentState("R1", (9, 5), None, 0, 0, [])}
assert run_pibt_step(idle, w)["R1"] == (9, 5)
at_goal = {"R1": PIBTAgentState("R1", (9, 5), (9, 5), 0, 0, [(9, 5)])}
assert run_pibt_step(at_goal, w)["R1"] == (9, 5)
push = {"H": PIBTAgentState("H", (9, 4), (9, 7), 0, 0, [(9, 4), (9, 5), (9, 6), (9, 7)]),
        "I": PIBTAgentState("I", (9, 5), None, 0, 5, [])}
m = run_pibt_step(push, w)
assert m["H"] == (9, 5) and m["I"] not in ((9, 5), (9, 4)), m

# Sim: no two robots spawn on the same cell
assert len(set(start_positions(20, w))) == 20

# --- Decentralized L3/L4: robots decide only from received messages -------------
from core import config
from sim.fast_sim import Bus, run, make_task_schedule


def fleet(specs, **flags):
    """specs: (id, pos, goal, base). Robots linked only through a message bus."""
    wm, bus, agents = demo_warehouse(), Bus(), {}
    for rid, pos, goal, base in specs:
        a = RobotAgent(rid, pos, wm, send=lambda m, rid=rid: bus.send(rid, m), priority_base=base)
        a.current_task, a.state = Task("T" + rid, pos, goal), "EN_ROUTE_TO_DROPOFF"
        agents[rid] = a
        bus.register(rid, a.on_message)
    return agents


def tick(agents):
    for a in agents.values():
        a.step()
    cells = [a.pos for a in agents.values()]
    assert len(cells) == len(set(cells)), f"collision {cells}"


config.USE_PIBT = True
try:
    # two robots racing for the same empty cell (9,5): no collision, no livelock
    ag = fleet([("A", (9, 4), (9, 9), 0), ("B", (8, 5), (10, 5), 1)])
    for _ in range(12):
        tick(ag)
    assert all(a.completed_tasks == 1 for a in ag.values()), [(a.pos, a.state) for a in ag.values()]
finally:
    config.USE_PIBT = False

config.USE_WAITFOR_GRAPH = True
try:
    # 4-robot ring deadlock: exactly one robot (lowest priority, R4) yields
    ring = [("R1", (4, 4), (4, 8), 0), ("R2", (4, 5), (8, 5), 1), ("R3", (5, 5), (5, 1), 2), ("R4", (5, 4), (0, 4), 3)]
    ag = fleet(ring)
    paths = {"R1": [(4, 4), (4, 5)], "R2": [(4, 5), (5, 5)], "R3": [(5, 5), (5, 4)], "R4": [(5, 4), (4, 4)]}
    for rid, a in ag.items():
        a.path = paths[rid] + [a.current_task.dropoff]
        a.t = 1  # positions already announced below, so skip the startup hello tick
        a._send_intent([a.pos] + a.path[1:], a.priority_base)
    tick(ag)
    yielded = [rid for rid, a in ag.items() if a.avoid_until]
    assert yielded == ["R4"], yielded
finally:
    config.USE_WAITFOR_GRAPH = False

# Baseline stop-and-wait must actually finish its tasks (not deadlock forever)
wb = demo_warehouse()
res = run(4, make_task_schedule(12, 7, wb), cooperative=False, max_ticks=1500, seed=7)
assert not res.get("timed_out") and res["collisions"] == 0, res

# L6: never more than one task per robot in a batch
bids = {"T1": {"R1": 1}, "T2": {"R1": 2}, "T3": {"R1": 3, "R2": 9}}
assert len(set(hungarian_batch_assign(bids, ["T1", "T2", "T3"]).values())) == 2

print("PASS: core/test_layers")
