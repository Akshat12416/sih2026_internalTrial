import time
from core.planner import WarehouseMap, ReservationBook, PeerIntent
from core.robot_agent import RobotAgent
from core.layouts import demo_warehouse

wmap = demo_warehouse()
book = ReservationBook("R3")
agent = RobotAgent("R3", 0, wmap, book, cooperative=True)
agent.send = lambda msg: None

agent.pos = (0, 9)
agent.state = "EN_ROUTE_TO_DROPOFF"
class DummyTask:
    dropoff = (4, 6)
agent.current_task = DummyTask()

agent.path = [(0, 9), (0, 8), (0, 7), (0, 6), (0, 5), (0, 4), (1, 4), (2, 4), (3, 4), (4, 4), (4, 5), (4, 6)]
agent.t = 94
agent.wait_ticks = 0

print("Before step:")
print(f"Path: {agent.path}")
agent.step()
print("After step:")
print(f"Path: {agent.path}")
