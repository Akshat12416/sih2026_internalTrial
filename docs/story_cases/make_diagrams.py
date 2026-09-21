"""Draws the story.md cases onto the 11x15 demo warehouse map.

The cases themselves live in `sim/scenarios.py` -- the same data the dashboard
case picker runs -- so a figure can never drift from what actually runs. Every
marked point is a real free cell and every drawn route is the actual A* path.

Run:  python -m docs.story_cases.make_diagrams
"""
from __future__ import annotations
import os
import textwrap
from collections import OrderedDict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, FancyArrow

from core.layouts import demo_warehouse
from core.planner import astar
from sim.scenarios import CASES

OUT = os.path.dirname(os.path.abspath(__file__))
CELL_COLOR = {0: "#f7f7f7", 1: "#5b6470", 2: "#ffe08a", 3: "#9ad7a0", 4: "#9fc5e8"}
ROBOT_COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]

FIGURE_TITLES = {
    "fig1_dispatch.png": "Figure 1 - Dispatch & bidding (L6 auction)",
    "fig2_collision.png": "Figure 2 - Collision safety & space-time routing (L2 / L5)",
    "fig3_standoff.png": "Figure 3 - Standoffs, livelock, goal yielding (L3 / L4)",
    "fig4_c1_c2.png": "Figure 4 - C1 directed graph & C2 PIBT",
    "fig5_c3_c4.png": "Figure 5 - C3 wait-for graph & C4 congestion routing",
    "fig6_c5_c6_l1.png": "Figure 6 - C5 D* Lite & L1 perception",
    "fig7_decentral.png": "Figure 7 - Decentralization (no central coordinator)",
}


def draw_map(ax, directed=False, title=""):
    w = demo_warehouse(directed=directed)
    for r in range(w.rows):
        for c in range(w.cols):
            ax.add_patch(Rectangle((c, r), 1, 1, facecolor=CELL_COLOR[w.grid[r][c]],
                                   edgecolor="#c9ccd1", linewidth=0.6))
            if w.grid[r][c] in (2, 3, 4):
                ax.text(c + .5, r + .5, {2: "P", 3: "D", 4: "C"}[w.grid[r][c]],
                        ha="center", va="center", fontsize=7, color="#333")
    if directed:
        for col, d in w.aisle_dir.items():
            ax.annotate("", xy=(col + .5, (7 if d > 0 else 1) + .5),
                        xytext=(col + .5, (1 if d > 0 else 7) + .5),
                        arrowprops=dict(arrowstyle="-|>", color="#2b78e4", lw=1.6, alpha=.55))
            ax.text(col + .5, -0.35, "N" if d < 0 else "S", ha="center",
                    fontsize=7, color="#2b78e4")
    ax.set_xlim(-0.4, w.cols)
    ax.set_ylim(w.rows + 4.2, -1.4)
    ax.set_xticks([x + .5 for x in range(w.cols)])
    ax.set_xticklabels(range(w.cols), fontsize=6)
    ax.xaxis.set_ticks_position("top")   # keep the bottom clear for the caption
    ax.set_yticks([y + .5 for y in range(w.rows)])
    ax.set_yticklabels(range(w.rows), fontsize=6)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=9, pad=14)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    return w


def draw_case(ax, case):
    # "after" mode decides whether this case is drawn on the directed graph
    flags = case.modes.get("after") or next(iter(case.modes.values()))
    w = draw_map(ax, flags.get("directed", False), f"{case.id} - {case.title}")

    for r, c in case.blocks:
        ax.add_patch(Rectangle((c, r), 1, 1, facecolor="none", edgecolor="#d62728",
                               hatch="xx", linewidth=1.2, zorder=3))

    for i, (label, start, goal, _prio) in enumerate(case.robots):
        col = ROBOT_COLORS[i % len(ROBOT_COLORS)]
        if goal is not None:
            path = astar(w, start, goal) or [start, goal]
            ax.plot([c + .5 for _, c in path], [r + .5 for r, _ in path],
                    color=col, lw=1.8, alpha=.75, ls="--", zorder=3)
            hr, hc = path[-1]
            pr, pc = path[-2] if len(path) > 1 else path[-1]
            ax.add_patch(FancyArrow(pc + .5, pr + .5, (hc - pc) * .45, (hr - pr) * .45,
                                    width=.02, head_width=.32, color=col, zorder=4))
            ax.add_patch(Rectangle((goal[1] + .12, goal[0] + .12), .76, .76, facecolor="none",
                                   edgecolor=col, lw=2, zorder=4))
            ax.text(goal[1] + .5, goal[0] + .5, label.replace("R", "") + "'",
                    ha="center", va="center", fontsize=7, color=col, zorder=5)
        ax.add_patch(Circle((start[1] + .5, start[0] + .5), .33, facecolor=col,
                            edgecolor="white", lw=1, zorder=5))
        ax.text(start[1] + .5, start[0] + .5, label.replace("R", ""),
                ha="center", va="center", fontsize=7, color="white", weight="bold", zorder=6)

    points = "  ".join(f"{rid}({s[0]},{s[1]})->({g[0]},{g[1]})" if g else f"{rid}({s[0]},{s[1]}) parked"
                       for rid, s, g, _ in case.robots)
    caption = (textwrap.fill(points, 74) + "\n\n"
               + textwrap.fill(case.note, 74) + "\n\n"
               + textwrap.fill("FIX: " + case.fix, 74))
    ax.text(0, w.rows + 0.8, caption, fontsize=7.2, va="top", family="monospace")


def main():
    groups = OrderedDict()
    for case in CASES:
        groups.setdefault(case.figure, []).append(case)

    for fname, cases in groups.items():
        fig, axes = plt.subplots(1, len(cases), figsize=(5.6 * len(cases), 7.2))
        for ax, case in zip([axes] if len(cases) == 1 else axes, cases):
            draw_case(ax, case)
        fig.suptitle(FIGURE_TITLES.get(fname, fname), fontsize=12, weight="bold")
        fig.tight_layout(rect=[0, 0, 1, .95])
        path = os.path.join(OUT, fname)
        fig.savefig(path, dpi=150, facecolor="white")
        plt.close(fig)
        print(f"wrote {path}  ({', '.join(c.id for c in cases)})")


if __name__ == "__main__":
    main()
