import time
from core.planner import WarehouseMap, ReservationBook
from core.robot_agent import RobotAgent
from core.layouts import demo_warehouse

wmap = demo_warehouse()
book = ReservationBook("R3")
agent = RobotAgent("R3", 0, wmap, book, cooperative=True)
agent.send = lambda msg: None

agent.pos = (0, 6)
agent.state = "EN_ROUTE_TO_DROPOFF"
class DummyTask:
    dropoff = (4, 6)
agent.current_task = DummyTask()

agent.path = [(0, 6), (0, 5), (0, 4), (1, 4), (2, 4), (3, 4), (4, 4), (4, 5), (4, 6)]
agent.t = 96
agent.wait_ticks = 0

print("Before step:")
print(f"Path: {agent.path}")
# We simulate modifying the condition to not check % 5
agent._replan()
if not agent.path or len(agent.path) >= 9:
    pass
else:
    print(f"Adopted path of length {len(agent.path)}")
    print(f"Path: {agent.path}")
