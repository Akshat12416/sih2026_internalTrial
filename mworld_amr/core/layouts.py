"""Reference warehouse floorplans. 0=free 1=shelf 2=pickup 3=dropoff 4=charge"""
from core.planner import WarehouseMap

def demo_warehouse() -> WarehouseMap:
    # 11 rows x 15 cols. Shelf rows create narrow single-width aisles
    # (choke points) between them -- deliberately, to stress-test conflict
    # resolution the way a real racking layout would.
    W, S = 0, 1
    grid = [
        [W, W, W, W, W, W, W, W, W, W, W, W, W, W, W],
        [W, W, S, S, W, S, S, W, S, S, W, S, S, W, W],
        [W, W, S, S, W, S, S, W, S, S, W, S, S, W, W],
        [W, W, S, S, W, S, S, W, S, S, W, S, S, W, W],
        [W, W, W, W, W, W, W, W, W, W, W, W, W, W, W],
        [W, W, S, S, W, S, S, W, S, S, W, S, S, W, W],
        [W, W, S, S, W, S, S, W, S, S, W, S, S, W, W],
        [W, W, S, S, W, S, S, W, S, S, W, S, S, W, W],
        [W, W, W, W, W, W, W, W, W, W, W, W, W, W, W],
        [W, W, W, W, W, W, W, W, W, W, W, W, W, W, W],
        [W, W, W, W, W, W, W, W, W, W, W, W, W, W, W],
    ]
    # pickup points along the bottom staging row
    for c in (2, 5, 8, 11):
        grid[9][c] = 2
    # dropoff / packing stations
    for c in (2, 8):
        grid[10][c] = 3
    # charging dock
    grid[10][12] = 4
    grid[10][13] = 4
    return WarehouseMap(grid)
