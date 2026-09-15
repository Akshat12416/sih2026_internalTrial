"""Reference warehouse floorplans. 0=free 1=shelf 2=pickup 3=dropoff 4=charge"""
import math
from typing import Optional
from core.planner import WarehouseMap


def build_warehouse(bays: int = 4, shelf_rows: int = 2, directed: Optional[bool] = None) -> WarehouseMap:
    """Racking layout: `bays` columns x `shelf_rows` rows of 2-wide x 3-tall shelf
    blocks, separated by single-width vertical aisles (choke points) and
    horizontal cross-corridors, with 2-lane perimeter columns on both sides.
      - top row: one pickup above every bay
      - bottom 3 rows: open staging area; dropoffs under even bays, chargers
        under odd bays (the 4-bay demo map keeps its 2-cell corner dock)
    bays=4, shelf_rows=2 is the original 11x15 demo map."""
    rows, cols = 4 * shelf_rows + 3, 3 * bays + 3
    grid = [[0] * cols for _ in range(rows)]
    for s in range(shelf_rows):
        for b in range(bays):
            for r in range(1 + 4 * s, 4 + 4 * s):
                grid[r][2 + 3 * b] = grid[r][3 + 3 * b] = 1
    last = rows - 1
    for b in range(bays):
        grid[0][2 + 3 * b] = 2
        if b % 2 == 0:
            grid[last][2 + 3 * b] = 3
    if bays <= 4:
        grid[last][cols - 3] = grid[last][cols - 2] = 4   # demo map: corner dock
    else:
        # bigger floors: a charger under every odd bay so no robot is ever more
        # than a few bays from one (a single corner dock is out of battery reach)
        for b in range(1, bays, 2):
            grid[last][2 + 3 * b] = 4
    return WarehouseMap(grid, directed=directed)


def demo_warehouse(directed: Optional[bool] = None) -> WarehouseMap:
    # 11 rows x 15 cols. Shelf rows create narrow single-width aisles
    # (choke points) between them -- deliberately, to stress-test conflict
    # resolution the way a real racking layout would.
    return build_warehouse(4, 2, directed)


def layout_for_fleet(n_robots: int):
    """(bays, shelf_rows) giving roughly constant floor space per robot.
    The demo map (~107 free cells) comfortably fits ~4 robots, so the
    warehouse grows with the fleet instead of cramming 10+ robots into it."""
    return max(4, n_robots + 1), max(2, math.ceil(n_robots / 3))
