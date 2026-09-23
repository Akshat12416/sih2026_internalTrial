import time
from core.planner import WarehouseMap, ReservationBook
from core.robot_agent import RobotAgent
from core.layouts import demo_warehouse

wmap = demo_warehouse()
book = ReservationBook("R3")
agent = RobotAgent("R3", 0, wmap, book, cooperative=True)
agent.send = lambda msg: None

# R3 is at (1, 4) at t=100
agent.pos = (1, 4)
agent.state = "EN_ROUTE_TO_DROPOFF"
class DummyTask:
    dropoff = (4, 6)
agent.current_task = DummyTask()

agent.path = [(1, 4), (2, 4), (3, 4), (4, 4), (4, 5), (4, 6)]
agent.t = 99
agent.wait_ticks = 0

print("Before step:")
print(f"Path: {agent.path}")
agent.step()
print("After step:")
print(f"Path: {agent.path}")
