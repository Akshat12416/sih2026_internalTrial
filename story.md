# Fleet Operations: The Journey of Decentralized Edge Coordination

This document chronicles the evolution of our decentralized robot swarm. As we built out the fleet, we encountered several complex edge cases that naturally arise when independent robots try to coordinate without a central server.

Below is the chronological story of the problems we faced, the scenarios that exposed them, and the technical solutions we implemented to solve them.

**Part 1 (cases 1–10)** is the original negotiation-era story. **Part 2 (cases 11–20)** covers everything added afterwards and recorded in `sesions.md` Part E: the layered architecture C1–C6, perception, the audit that corrected several of our own numbers, and the removal of the central coordinator.

---

## How to read the maps

Every case below has a diagram with **real, simulatable cell coordinates** marked on the demo warehouse floor. Diagrams live in [docs/story_cases/](docs/story_cases/) and are regenerated with:

```bash
python -m docs.story_cases.make_diagrams
```

The demo map is `core.layouts.demo_warehouse()` — 11 rows × 15 cols, addressed `(row, col)`:

```
col:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14
row0  .  .  P  .  .  P  .  .  P  .  .  P  .  .  .     P = pickup   (0,2) (0,5) (0,8) (0,11)
row1  .  .  #  #  .  #  #  .  #  #  .  #  #  .  .     D = dropoff  (10,2) (10,8)
row2  .  .  #  #  .  #  #  .  #  #  .  #  #  .  .     C = charger  (10,12) (10,13)
row3  .  .  #  #  .  #  #  .  #  #  .  #  #  .  .     # = shelf
row4  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .     rows 0,4,8,9,10 = open corridors
row5  .  .  #  #  .  #  #  .  #  #  .  #  #  .  .     cols 4,7,10 = single-width aisles
row6  .  .  #  #  .  #  #  .  #  #  .  #  #  .  .     cols 0,1,13,14 = perimeter lanes
row7  .  .  #  #  .  #  #  .  #  #  .  #  #  .  .
row8  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .     one-way (C1): col4 N, col7 S, col10 N
row9  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .
row10 .  .  D  .  .  .  .  .  D  .  .  .  C  C  .
```

In every diagram: **filled circle = start (A)**, **outlined square = goal (B)**, **dashed line = the actual A\* route** between them, **red hatched cell = a blockage**.

| Figure | Cases | File |
|---|---|---|
| 1 | case1, case5, case7 — dispatch & bidding | [fig1_dispatch.png](docs/story_cases/fig1_dispatch.png) |
| 2 | case2, case3 — collision safety & space-time routing | [fig2_collision.png](docs/story_cases/fig2_collision.png) |
| 3 | case4, case6, case10 — standoffs, livelock, goal yielding | [fig3_standoff.png](docs/story_cases/fig3_standoff.png) |
| 4 | case11, case12a, case12b — directed graph & PIBT | [fig4_c1_c2.png](docs/story_cases/fig4_c1_c2.png) |
| 5 | case13, case14 — wait-for graph & congestion routing | [fig5_c3_c4.png](docs/story_cases/fig5_c3_c4.png) |
| 6 | case15, case17 — D\* Lite & perception | [fig6_c5_c6_l1.png](docs/story_cases/fig6_c5_c6_l1.png) |
| 7 | case19 — decentralized L2 race | [fig7_decentral.png](docs/story_cases/fig7_decentral.png) |

## Running a case (one click, or one command)

The cases are not prose — they are data in [sim/scenarios.py](sim/scenarios.py), and that one
file feeds the figures, the dashboard and the CLI, so a diagram can never drift from what runs.

**Dashboard:** the case picker sits in the right-hand side panel, under **Story Cases**, so the
3D view, the 2D grid and the picker are all on screen at once. Tick the cases you want — their
start and goal cells mark on the map immediately, in 2D **and** on the 3D floor — then hit
**Run selected**.

The player is built for recording a walkthrough, not for a jump cut: the robots **walk from
wherever they are standing** to the case's start cells (real A\* routes), the case plays, and the
next case walks them on from where the last one left them. Nothing teleports. A caption over the
map names the case and the phase, both views glide between cells, and the final frame is held
until you press **Back to live**.

```bash
python -m live.orchestrator --robots 3 --full     # robots + dashboard; open http://127.0.0.1:8000
```

Start it this way, **not** with `python -m dashboard.server` on its own. The dashboard is a
passive observer of the UDP mesh — by itself it runs no robots, so the grid is empty and
Send Queue broadcasts to ports nobody is bound to. The orchestrator launches the robot processes
*and* the dashboard. If a stale dashboard is still holding the ports the orchestrator now says so
and exits instead of half-starting; use `--web-port 8010 --observer-port 9610` to run a second one.

Story Cases still work with no fleet running (they execute server-side), but nothing else will.

**CLI:**

```bash
python -m sim.scenarios --list
python -m sim.scenarios --case case12a --mode before
python -m sim.scenarios --case case12a --mode after
```

Cases whose fix is unconditional (everything in Part 1) have a single `after` mode — there is no
flag to turn those fixes off. Part 2 cases sit behind feature flags, so they have both.

# Part 1 — The negotiation era (cases 1–10)

## 1. Adding Dropoff to Bidding Cost

**Map:** Figure 1, left panel. Task pickup **P(0,5)** → dropoff **D(10,2)**. R1 starts **(0,4)**, R2 starts **(9,4)**.

**The Scenario:**
A new task was announced. Robot A was very close to the pickup location, but the dropoff location was on the complete opposite side of the warehouse. Robot B was slightly further from the pickup, but its path to the pickup perfectly aligned with the dropoff location. Robot A won the bid, resulting in a massively inefficient cross-warehouse trip.

**The Problem:**
Originally, robots only calculated their bid cost based on the distance from their current location to the *pickup* point. The actual delivery (dropoff) location was completely ignored during the auction.

**The Solution:**
We updated the bidding calculation in the Contract Net Protocol. Bids now include the full A* path cost from the robot's current position to the pickup, *plus* the estimated distance from the pickup to the dropoff. This ensures the robot with the most efficient overall trip wins the job.

---

## 2. Robots Phasing Through Each Other (Absolute Occupancy)

**Map:** Figure 2, left panel. R1 **(8,7) → (0,7)** through aisle col 7; R2 parked at **(6,7)** claiming it will vacate.

**The Scenario:**
Robots were crossing paths in narrow aisles. Instead of yielding or waiting, they would literally drive over each other, occupying the exact same cell at the exact same time.

**The Problem:**
Robots were relying on what peers *said* they were going to do. If Robot A was in a cell but broadcasted an intent to move out of it next tick, Robot B would optimistically assume the cell would be free and move into it. If Robot A got delayed, they collided. A peer's stated intent to vacate is not a guarantee.

**The Solution:**
We added a strict Absolute Occupancy check in `resolve_conflict`. Rule 1: A robot will *never* move into a cell that any peer is confirmed to currently occupy, regardless of what that peer's future path claims. This conservative rule guarantees zero collisions without needing a centralized server.

---

## 3. Space-Time Reservation (Cooperative A*)

**Map:** Figure 2, right panel. R1 **(4,1) → (4,13)** along the row-4 corridor, R2 **(0,7) → (8,7)** down aisle col 7; they cross at **(4,7)**.

**The Scenario:**
Robots were constantly stopping and starting, unable to navigate around each other smoothly. They were planning paths blindly as if they were the only robot in the warehouse, only stopping when they literally bumped into a peer.

**The Problem:**
The naive "stop-and-wait" baseline planner ignores peers' future intent. It only reacts to immediate physical blockages, making routing highly inefficient in crowded spaces.

**The Solution:**
We implemented the `ReservationBook` and **Space-Time A***. Each robot broadcasts a 6-tick future "intent" (its planned path). Peers store this in their local `ReservationBook`. When a robot runs A*, it checks this book and avoids stepping into a specific cell at a specific future timestep if another robot has already claimed it. This allows decentralized, lock-free routing where robots weave around each other seamlessly.

---

## 4. The "Impatient Honking" Paralysis & Premature Yielding

**Map:** Figure 3, left panel. R5 **(8,4) → (0,4)**; IDLE R3 parked mid-aisle at **(5,4)**.

**The Scenario:**
Robot 5 (R5) received a job but its path was blocked by Robot 3 (R3), which was sitting completely `IDLE`. R5 would ask R3 to move aside. R3 would agree and start moving. However, before R3 could fully get out of the way, R5 would recalculate its path, give up on the aisle entirely, and take a massive, battery-draining detour around the entire warehouse shelf.

**The Problem:**
There were two issues here:
1. **Low Starvation Limit:** Active robots were too impatient. If their path was blocked, they would only wait a few ticks before giving up and recalculating a detour.
2. **Honk Paralysis:** When the `IDLE` robot (R3) was trying to move out of the way, the active robot (R5) would continuously send "nudges" (honks) every tick. These continuous nudges were interrupting R3's escape plan, forcing it to freeze and recalculate constantly, trapping both robots.

**The Solution:**
- We increased the `STARVATION_WAIT_LIMIT` to 10 ticks, giving `IDLE` robots enough time to physically step out of the way before the active robot decides to detour.
- We implemented **Honk Ignoring**. When an `IDLE` robot is nudged, it runs an A* search to find the nearest staging cell, generates a multi-step escape path, and enters a `MAKING WAY` state. While in this state, it is smart enough to completely ignore any further nudges from the impatient blocked peer. It does not stop to recalculate; it just focuses on finishing its escape steps, allowing it to smoothly clear the aisle.

---

## 5. The Battery Dominance Flaw

**Map:** Figure 1, middle panel. Task pickup **(10,8)**; R3 at **(9,8)** with 70% battery, R5 at **(8,13)** with 95%.

**The Scenario:**
A new task popped up right next to R3. R3 was at 70% battery, which is plenty of power to finish the job. However, R5 was sitting across the warehouse at 95% battery. Because the auction system weighed battery levels strictly linearly, R5's extra 25% battery allowed it to outbid R3. R5 ended up driving all the way across the map to do R3's job, wasting massive amounts of time and overall fleet energy.

**The Problem:**
The battery penalty in the Contract Net Protocol auction was linear. A robot with 100% battery would always aggressively outbid a robot with 70% battery, regardless of how efficient the dispatch was. We needed a system where a 70% charged robot is considered "healthy enough" to win based on distance.

**The Solution:**
We implemented a **Non-Linear (Quadratic) Battery Penalty**.
- If a robot has more than `60%` battery, its battery penalty is `0`. It competes purely on distance and efficiency.
- If a robot dips below `60%`, the penalty scales quadratically. This heavily suppresses low-battery robots from taking jobs, saving their power for charging trips, while letting all healthy robots compete strictly on spatial logic.

---

## 6. The Symmetric Livelock (Head-to-Head Standoff)

**Map:** Figure 3, middle panel. R2 **(4,1) → (4,13)** and R4 **(4,13) → (4,1)**, head-on in the row-4 corridor.

**The Scenario:**
R2 and R4 were both actively carrying packages (`EN_ROUTE`) and met head-to-head in a narrow, 1-wide horizontal aisle. Because both were busy, neither was willing to accept a nudge (which are only for `IDLE` robots). They entered a standoff. After 10 ticks, they both got frustrated at the *exact same time*, both backed up, and both took parallel detours to the next aisle... where they met head-to-head *again*. They were locked in an endless cycle.

**The Problem:**
This is a classic decentralized robotics problem called **Symmetric Livelock**.
1. **Symmetry:** Both robots had the exact same `STARVATION_WAIT_LIMIT` of 10 ticks. They timed out on the exact same tick, making mirroring decisions.
2. **A* Stubbornness:** When they recalculated, the A* algorithm realized the blockage was only temporary (20 ticks). It mathematically calculated that waiting in place for 20 ticks was cheaper than backing out and going around the shelf. So, they never actually backed out of the choke point.

**The Solution:**
- **Symmetry Breaking:** We made the starvation limit dynamic based on the robot's ID/Priority (`10 + (5 - priority_base) * 4`). Now, higher-priority robots are "stubborn" and will wait up to 26 ticks. Lower-priority robots are "impatient" and give up at 18 ticks. The impatient robot always yields first, breaking the symmetry.
- **Forced Detours:** When a robot hits starvation and blacklists a cell, it now tells the A* planner that the cell is blocked for **400 ticks** (the entire planning horizon). This mathematically forces the A* algorithm to find a spatial detour (putting it in reverse) rather than just waiting in place for the blacklist to expire.

---

## 7. Inefficient Dispatching: The Need for Predictive Bidding

**Map:** Figure 1, right panel. R4 is mid-trip **(4,4) → D(10,8)**; new task pickup at **(10,10)**; idle R6 sits at **(8,1)**.

**The Scenario:**
R4 was currently dropping off a package. A new task was announced with a pickup location just 2 cells away from R4's current dropoff. However, because R4 was currently busy (`EN_ROUTE_TO_DROPOFF`), it wasn't allowed to bid. Instead, a distant `IDLE` robot won the job and had to travel 15 cells to reach the pickup.

**The Problem:**
Robots were strictly filtered from participating in auctions unless their state was `IDLE`. This missed massive optimization opportunities for "task chaining," where a robot finishing a job is the physically closest candidate for the next job.

**The Solution:**
We implemented **Task Queueing and Predictive Bidding**.
- Busy robots are now allowed to bid on future tasks if they have room in their `queued_tasks` list.
- They calculate a predictive bid: `time_remaining_on_current_task + distance_from_dropoff_to_new_pickup`.
- When they win, the task is appended to their queue.
- The exact millisecond they drop off their current package, they instantly check their queue and transition straight back to `EN_ROUTE_TO_PICKUP`, seamlessly chaining the jobs together.

---

## 8. The "Split-Brain" Bidding Race Condition

**The Scenario:**
A new task was announced. R4 (busy and moving) and R3 (idle) both bid on it. R4 had the mathematically lower bid. However, the UI reported that the auction was `WON BY R3`. Worse, R4 *also* thought it won, so both robots claimed the task and started moving for the exact same package!

**The Problem:**
The auction window stays open for 3 ticks. Because `bid_on_open_tasks()` ran every single tick, robots were submitting updated bids 3 times in a row.
- R3 was idle, so its bid stayed constant (e.g., `15, 15, 15`).
- R4 was moving, so its distance to its dropoff was decreasing every tick. It submitted shifting bids: `16`, then `15`, then `14`.
Due to slight UDP network delays, R3's auction window closed when it had only received R4's `15` bid (so R3 won the `15 vs 15` tiebreaker). R4's window closed after it registered its own `14` bid, so R4 thought it won.

**The Solution:**
We implemented a strict **Single-Bid Rule**. Robots now check if they have already submitted a bid for a specific `task_id`. If they have, they do not bid again. By evaluating their cost exactly once and standing by it for the entire 3-tick window, the bids are perfectly stable, entirely eliminating the split-brain race condition.

---

## 9. The Auction Window Head-Start Discrepancy

**Map:** Figure 1, right panel (same setup as case 7).

**The Scenario:**
While monitoring the predictive bidding, we noticed an unfair advantage. When a task is announced, an `IDLE` robot sits completely still for the 3-tick auction window, waiting to see if it wins. But a busy robot doesn't pause—it keeps driving towards its dropoff during those 3 ticks!

**The Problem:**
Because the busy robot was actively making progress during the auction, its bid (calculated as "distance from now") was artificially high. By the time the 3-tick auction actually settled, the busy robot was physically 3 steps closer to its goal than its initial bid implied.

**The Solution:**
We applied an **Auction Window Discount**. When a busy robot calculates its predictive `ticks_to_finish`, we automatically subtract `AUCTION_WINDOW_TICKS` (3) from its cost. This perfectly aligns their bid with their true arrival time, giving them credit for the momentum they carry through the auction window.

---

## 10. The Head-to-Head Active Deadlock & Goal Yielding

**Map:** Figure 3, right panel. Loaded R3 stands on pickup **P(0,5)** heading for **D(10,2)**; R1 at **(0,4)** and R5 at **(0,7)** both want **P(0,5)**. Row 0 is one cell wide.

**The Scenario:**
A situation arose during high traffic where multiple robots ended up nose-to-nose in a single-width aisle at the pickup station. Robot 3 (R3) had just picked up a task and was trying to leave the row. However, Robot 1 (R1) and Robot 5 (R5) were empty and aggressively trying to enter the exact same row to pick up new tasks. They collided in a 1-wide aisle, with R3 completely boxed in.

**The Problem:**
Our system had a dynamic starvation limit which forces a blocked robot to eventually blacklist the cell in front of it and calculate a detour. However, we had a safety check that prevented a robot from *ever* blacklisting its final goal cell (because doing so would make the pathfinder fail).
Because the cell they were fighting over was the actual pickup goal for R1 and R5, they refused to blacklist it. Instead, they would reset their timers, recalculate the exact same path to their goal, realize it was still occupied by R3, and start waiting again. This created a permanent infinite loop where nobody would back down!

**The Solution:**
- We removed the rule preventing a robot from blacklisting its own goal. If a goal is hopelessly blocked, it *should* be blacklisted.
- We implemented **Goal Yielding**: if a robot's pathfinder fails (which now happens if its goal is blacklisted), it temporarily gives up on its mission, finds the nearest `FREE` staging area, and drives there to wait it out.
- Now, when R1 realizes it can't reach the pickup station because R3 is blocking it, R1 gracefully reverses out of the aisle, "circles the block" by waiting at a staging cell, and allows R3 to leave before trying again!

---

# Part 2 — The layered architecture (cases 11–20)

Everything above solved *correctness*: no collisions, no permanent deadlocks. What it did **not** solve was *latency*. Every 2–3 robot encounter still cost roughly **5–6 seconds** of honking, waiting and starvation timers. Part 2 is the rewrite that attacked that, layer by layer, and then the audit that told us which of our own numbers were real. The full engineering log lives in [sesions.md](sesions.md) Part E.

---

## 11. C1 — Head-On Conflicts That Should Never Have Been Possible

**Map:** Figure 4, left panel (`case11`). R1 **(8,7) → (0,7)** and R2 **(0,7) → (8,7)** — both inside aisle col 7, nose to nose. Blue arrows show the enforced aisle directions.

**The Scenario:**
Two robots enter the same single-width storage aisle from opposite ends. Neither can pass. Every mechanism from Part 1 fires — nudge, wait, starvation, blacklist, detour — and the aisle still costs seconds to clear, over and over, all day.

**The Problem:**
We were solving head-on conflicts at runtime that the *floor plan itself* was creating. A one-cell-wide aisle with traffic in both directions is a structural defect, not a coordination puzzle.

**The Solution:**
A **directed guidance graph** (`core/config.USE_DIRECTED_GRAPH`). `WarehouseMap.neighbours()` makes single-width vertical aisles one-way, alternating left to right: **col 4 northbound, col 7 southbound, col 10 northbound**. Cross-corridors (rows 0, 4, 8, 9, 10) and perimeter lanes stay two-way. Head-on inside an aisle becomes *unrepresentable* rather than resolvable.

**Result:** on `case11` itself, **49 → 15 ticks**. Fleet-wide: single-width aisle head-ons **532 → 0**, completion **537.6 → 420.6 ticks (+21.8%)**.
**Caveat:** it does nothing for crossing conflicts or same-direction queuing in the two-way corridors. Those are L4's job.

**Simulate it:** `python -m sim.fast_sim --compare-directed`

---

## 12. C2 — Replacing Multi-Round Negotiation with PIBT

**Map:** Figure 4, middle + right panels.
- `case12a` head-on: R1 **(4,1) → (4,7)**, R2 **(4,7) → (4,1)**.
- `case12b` 3-robot crossing at **(4,7)**: R1 **(1,7) → (7,7)**, R2 **(4,4) → (4,10)**, R3 **(7,7) → (1,7)**.

**The Scenario:**
Three robots meet at the row-4 / col-7 intersection. Each honks, each waits, each times out at a different tick, each replans — and the intersection takes tens of ticks to drain.

**The Problem:**
The negotiation protocol needed *multiple message rounds* to converge, and each round costs a tick. Its cost grows with the number of robots involved, exactly when you can least afford it.

**The Solution:**
**PIBT** (Priority Inheritance with Backtracking) in `core/pibt.py`. In one timestep, the highest-ranked robot claims its desired cell; whoever holds that cell inherits its priority and is recursively pushed; backtracking undoes a branch that cannot be satisfied. Swap collisions are rejected outright. No negotiation rounds, no timers — one deterministic decision per tick.

The priority key went through three versions before it was stable:
1. **wait-count rank** — livelocked, because a fresh broadcast was compared against a stale one.
2. **distance to goal** — livelocked, because robots pushed each other back and forth.
3. **`rank = (goal_since, priority_base, robot_id)`** — the PIBT paper's rule: longest-without-reaching-goal goes first. It is *constant until the goal changes*, so two robots comparing broadcasts one tick apart still reach the same answer.

**Result:** `case12a` **47 → 15 ticks** (delay vs free-flow **41 → 9**, wait **55 → 0**); `case12b` **45 → 15 ticks** (delay **39 → 9**). Fleet: **537.6 → 217.0 ticks (+59.6%)**, wait ticks **865 → 6**. The single biggest win in the project.
**Caveat:** PIBT guarantees *reachability*, not collision freedom. The L2 absolute-occupancy shield (case 2) keeps independent veto authority over every move PIBT proposes.

**Simulate it:** `python -m sim.bench_conflicts` and `python -m sim.fast_sim --compare-pibt`

---

## 13. C3 — Deadlock Detection Instead of Deadlock Timeouts

**Map:** Figure 5, left panel (`case13`). A true 4-cycle in the open staging block — each robot's *next* cell is the next robot's *current* cell, but every goal is escapable: R1 **(8,4)→(8,8)**, R2 **(8,5)→(10,5)**, R3 **(9,5)→(9,1)**, R4 **(9,4)→(4,4)**.

**The Scenario:**
Four robots each want the cell the next one is standing on. Nobody is broken, nobody is stuck against a wall — they are waiting on each other in a perfect ring, and no local rule can see it.

**The Problem:**
Our only answer was the starvation timer: burn 18–26 ticks, then have somebody blacklist and detour. That is 4–6 seconds of a fleet standing still, *per deadlock*, for a condition that is mathematically detectable the instant it forms.

**The Solution:**
A **wait-for graph** (`core/deadlock.py`). Each robot builds the directed graph *A → B* ("A is waiting on a resource B holds") from the intents it has received, and runs 3-colour DFS cycle detection in O(V+E). If a cycle exists, the victim is chosen deterministically via `apply_aging(wait_ticks, priority_base)` — so every robot in the ring computes the *same* victim, and only that robot yields.

**Result:** `case13` runs **32 → 9 ticks** with WFG + PIBT enabled. Fleet: **537.6 → 335.8 ticks (+37.5%)**; the isolated deadlock bench reports recovery **19 ticks → 1 tick** with exactly one robot yielding.

**Caveat — and this one is uncomfortable.** Re-running `case13` layer by layer:

| flags | ticks |
|---|---|
| legacy (starvation timeout) | 32 |
| WFG only | 33 |
| PIBT only | **9** |
| WFG + PIBT | **9** |

On *this* ring, **PIBT does the work and WFG alone shows no gain.** PIBT can rotate the ring out
in one step, which is exactly the case WFG was built for, so WFG never gets to fire. WFG earns
its place on rings PIBT cannot rotate — not on this one. Reproduce it with
`python -m sim.scenarios --case case13 --mode before|after`.

WFG only finds circular resource waits; transient crossing encounters are still L4's job, and physical safety is still L2's.

**Simulate it:** `python -m sim.bench_deadlock` and `python -m sim.fast_sim --compare-wfg`

---

## 14. C4 — Everybody Takes the Same Shortest Path

**Map:** Figure 5, right panel (`case14`). Four robots leave the staging row for four different top bays: R1 **(10,2)→(0,5)**, R2 **(10,3)→(0,8)**, R3 **(10,4)→(0,11)**, R4 **(10,5)→(0,2)**.

**The Scenario:**
Three robots in the staging area all get tasks near the top-left bays. A* is optimal, deterministic, and identical for all three, so all three route through aisle col 4 — and queue nose-to-tail in a one-wide aisle while cols 7 and 10 sit empty.

**The Problem:**
A shortest path that is optimal for one robot is pathological for a fleet. The planner had no notion that a cell can be *popular*.

**The Solution:**
**Congestion-aware routing.** `build_congestion_heatmap()` turns peer intent broadcasts into a cell-level forward traffic density map with temporal decay. A*'s step cost becomes `1.0 + α · congestion(next)`, so a slightly longer empty aisle beats a shorter crowded one. It is a *recommendation* layer — pure cost shaping, no safety authority.

**Result:** `case14` **54 → 19 ticks** (delay vs free-flow **37 → 2**). Fleet: **537.6 → 339.6 ticks (+36.8%)**.
**Caveat:** it depends entirely on L0 broadcasts. If comms drop, the heatmap is empty and A* degrades gracefully to plain geometric shortest path.

**Simulate it:** `python -m sim.fast_sim --compare-congestion`

---

## 15. C5 — Replanning Cost on an Embedded Board

**Map:** Figure 6, left panel. R1 **(8,4) → (0,4)**; a pallet drops on **(2,4)** mid-trip (hatched).

**The Scenario:**
A pallet falls into an aisle a robot is already committed to. The robot must replan — and on a Jetson Nano or a Pi 4, re-expanding the whole grid for a single changed cell is pure waste, repeated on every blockage event.

**The Problem:**
Full A* from scratch throws away a search tree that is still 99% valid. Only the vertices *downstream of the blocked cell* are actually inconsistent.

**The Solution:**
**D\* Lite** (`core/dstar_lite.py`, Koenig & Likhachev): search backwards from the goal, keep the search tree between calls, and repair only the vertices where `rhs(s) ≠ g(s)`, using the `k_m` key modifier to absorb robot movement. About **17 node expansions** per blockage event, and 100% identical path length to full A*.

**Result — and this is where we corrected ourselves.** The original entry claimed a clean win. Re-measured honestly:
- undirected graph: **slower** than A* (90 → 152 μs),
- directed graph: **13% faster** (146 → 127 μs).

On a small 11×15 map, D\* Lite's bookkeeping overhead eats its own savings. It is kept because the benefit scales with map size, and the scaled floors (case 20) are where it starts to pay.
**Caveat:** D\* Lite optimizes *changing edge costs*. A brand-new goal still forces a fresh search.

**Simulate it:** `python -m sim.bench_dstar` and `python -m sim.fast_sim --compare-dstar`

---

## 16. C6 — Greedy Dispatch Leaves Money on the Table

**Map:** Figure 6, middle panel. R1 at **(8,1)** takes the far task at **(0,11)**, R2 at **(8,13)** takes the far task at **(0,2)** — the two routes cross the whole floor. The batched solution swaps them.

**The Scenario:**
Two tasks are announced within a tick of each other. Each is auctioned the moment it arrives, so each goes to whoever happens to bid best *at that instant* — and the fleet ends up with two robots crossing past each other.

**The Problem:**
First-dispatch auctioning is greedy. A locally optimal assignment made task-by-task is not the globally optimal assignment over the set.

**The Solution:**
**Hungarian batch assignment** (`core/auction.py`). Pool the open bids over a short accumulation window (≈6 ticks) and solve min-cost bipartite matching with Kuhn–Munkres.

**Result — honest:** allocation quality on the isolated benchmark is genuinely better (**95.7 → 93.0 mean travel steps, 100% Pareto-optimal matching**). End-to-end fleet impact is **+0.9%, within noise**, and in the audit run the wait metric got slightly *worse*. Batching only pays when tasks actually arrive in bursts; at <1 task per 10 ticks it degenerates to first-dispatch by construction.
**Caveat kept from the audit:** we do not claim a fleet-level speedup for C6 on this workload.

**Simulate it:** `python -m sim.bench_batching` and `python -m sim.fast_sim --compare-batching`

---

## 17. L1 — The Robot That Could Only See What the Map Already Knew

**Map:** Figure 6, right panel. R1 **(8,7) → (0,7)**; an unmapped obstacle sits at **(5,7)** (hatched).

**The Scenario:**
A dropped pallet, a stray cage, a person — an obstacle that is physically there but is not in the static grid every robot was flashed with.

**The Problem (and the bug):**
`core/perception.py` implements an edge-AI detector (YOLOv8-nano stub): a forward FOV cone scan, per-detection confidence `p ∈ [0.82, 0.98]`, and multi-frame temporal hysteresis so one noisy frame cannot block an aisle. But the first integration **scanned the robot's own map instead of physical ground truth** — so it could only "see" obstacles the map already contained, and then skipped reporting them as already-known. L1 never fired once. It looked like it worked because nothing ever crashed.

**The Solution:**
Perception now scans `sensor_truth`, injected by the simulator or by the real sensor driver — i.e. the physical world, not our belief about it. A confirmed detection is handled exactly like a peer alert: **mark the local map → replan → broadcast to peers over L0**.

This is the golden rule of the whole stack, stated concretely: **AI recommends (L1 perception, L5 congestion, L6 bids); deterministic layers decide and veto (L2 shield, L3 WFG, L4 PIBT).** A 0.82-confidence neural detection may never override the occupancy shield.

**Simulate it:** `python -m sim.bench_matrix`

---

## 18. The Audit — When the Benchmark Is the Bug

**The Scenario:**
By the end of Session 7 we had a table of extremely flattering numbers: "+88.2% speedup", "47,721 baseline collisions", "1 tick (0.25s) conflict resolution". A code audit went looking for where they came from.

**The Problem:**
Several of them came from **our own bugs and flawed metrics, not from the algorithms**:

| Claimed | Actually |
|---|---|
| 47,721 / 8,500 baseline collisions at 10–20 AMRs | A **spawn bug** — robots 7+ were spawning *on top of* robots 1–6. With unique spawn cells the baseline's collisions are **0**. |
| Conflict resolution "1 tick (0.25s)" | A measurement artifact: the conflict window defaulted to 1 tick. The honest metric is *delay vs free-flow trip*: **36 → 8 ticks**. |
| PIBT 347.4 / 289.8 ticks | Included an **idle-robot jitter bug** — idle robots and robots already at their goal were being moved one cell every single tick. |
| D\* Lite "943 → 761 wait ticks" | Came from a different run than the one it was logged under. |
| Baseline "timed out" at 2000 ticks | True, but it completed **0–2 tasks** — it deadlocked almost immediately. Any "X% faster" against it is meaningless. |
| L1 perception working | Never fired (case 17). |
| Hard-coded "(Zero collisions)" labels in output | Printed unconditionally, whether or not there were collisions. |

Plus a real logic bug in `core/auction.py`: unmatched tasks were being handed to an **already-matched robot** as a fallback.

**The Solution:**
- Fixed the root causes: `start_positions()` gives unique spawns; idle/at-goal robots stay put instead of jittering, and park out of the fleet's way (see case 21); the auction fallback was removed (unmatched tasks stay open for the next batch); perception reads real sensor truth.
- Removed every hard-coded success label from the benchmark output, and made runs that hit the tick limit **report as timeouts**.
- Replaced the fake conflict metric with **delay vs free-flow trip**.
- Added `core/test_layers.py` regression checks so these cannot silently return.

**The lesson worth keeping:** a benchmark that only ever produces good news is not a benchmark. Every headline number in [sesions.md](sesions.md) Part E after 2026-09-16 is a re-measured one, and the caveats are recorded next to them.

**Verify it:** `python -m core.test_layers`

---

## 19. Removing the Central Coordinator (and the Four Bugs It Was Hiding)

**Map:** Figure 7 — all three panels.

**The Scenario:**
The demo was fast, deadlock-free and collision-free. Then we looked at *where the code ran*: `sim/fast_sim.py` was calling `run_pibt_step()` and a fleet-wide deadlock resolver **over all robots at once, with one global view**. Meanwhile `live/robot_process.py` — the actual robot — just called plain `agent.step()`. The impressive layers only existed in the simulator's god-mode, and the project's entire premise is *decentralized edge coordination*.

**The Problem:**
A global view hides every hard problem in distributed robotics: disagreement, staleness, and simultaneity. Removing it exposed four real bugs at once.

**The Solution — L3 and L4 moved inside `RobotAgent.step()`.** The simulator and the live UDP process now run the *exact same code path*. Nothing anywhere has a fleet-wide view.

- **Local PIBT** (Figure 7, left) — `_local_pibt_move()` runs PIBT over itself plus only those peers within `PIBT_LOCAL_RADIUS = 4` cells, and applies **only its own move**. In the diagram R1 and R2 are inside each other's radius and resolve together; R5 at (10,13) is outside it and is never considered.
- **Local WFG** — `_yield_if_deadlock_victim()` builds the wait-for graph from its own received intents and yields only if *it* is the cycle's deterministic victim. Intent messages now carry `goal` and `rank` so peers can compute this independently.
- **The L2 race rule** (Figure 7, middle) — two robots intending to enter the *same empty cell* on the same tick over an unsynchronised radio. Neither is occupying it, so absolute occupancy says nothing. New symmetric rule: **yield if a peer with a better broadcast rank intends the same empty cell.** Because it is symmetric, exactly one robot enters.
- **Hello tick** — every robot announces its position on its first tick *before it ever moves*. This fixed tick-1 spawn collisions, where robots moved before anyone knew where anyone was.
- **Stall fallback** — local views differ slightly, so after `PIBT_STALL_TICKS = 2` held ticks with an empty next cell, the L2 shield arbitrates instead of waiting for consensus that will not come.

**Two genuine bugs fixed on the way:**
1. **PIBT push overwrite** (present since C2): a *lower*-priority agent could push a robot whose move had already been decided, silently overwriting it.
2. **Stale path after a push**: a pushed robot kept its old path, because position was updated *before* the "did I move?" check ran.

**Plus a fleet policy fix** (Figure 7, right): idle robots used to camp around dropoff **D(10,8)** and wall it off permanently. All modes — baseline included — now move idle robots out of the way. The first version sent them to the perimeter lanes; case 21 replaced that.

**Result:** all C1–C6 numbers in case 11–16 above are from this decentralized implementation. Live: **3 separate OS processes over UDP, full stack, 150 ticks → 8 tasks completed, 0 same-tick shared cells.**

**Caveat (the honest one):** safety still ultimately rests on the L2 shield, which is *exact* when robots step one after another, as they do in the sim. Over real async radio it depends on intents arriving — and a robot pushed sideways by PIBT moves to a cell that was **not in its broadcast intent**, so a race against a robot entering that same cell cannot be ruled out from messages alone. **Physical sensing (L1) is the backstop, not the messages.**

**Run it:** `python -m live.orchestrator --full` (or `--features pibt,wfg,congestion,...`)

---

## 20. A Baseline That Actually Finishes, and Floors That Actually Fit

**The Scenario:**
"Our system is 88% faster than the baseline." Faster than *what*, exactly? Our stop-and-wait baseline deadlocked within a few dozen ticks and completed 0–2 tasks out of 24. We were comparing against a system that does not work.

**The Problem:**
Two separate distortions:
1. **A strawman baseline.** A baseline that never finishes makes any speedup figure a function of the tick limit, not of our algorithms.
2. **A fixed 11×15 floor for every fleet size.** Running 20 AMRs on the demo map measures how bad a traffic jam gets, not how the coordination scales. Space per robot was collapsing from ~35 free cells to ~5.

**The Solution:**
- **A real stop-and-wait baseline:** after `BASELINE_WAIT_TIMEOUT + 2*(priority_base % 5)` blocked ticks — a staggered backoff, which is what breaks the symmetry — a robot detours around the blocked cell. It still has **no intent sharing, no reservations, no priority negotiation**. That is the honest "naive fleet" to beat, and it now completes its tasks.
- **Scaled warehouses:** `core/layouts.build_warehouse(bays, shelf_rows)` and `layout_for_fleet(n)` size the floor to the fleet (3→11×15, 5→11×21, 10→19×36; **31–42 free cells per robot**). One-way aisles are now *auto-detected* (a free cell with shelves on both sides) and alternate N/S, producing edges byte-identical to the old hard-coded cols 4/7/10 on the demo map. Bigger floors get a charger under every odd bay, since a single corner dock is out of battery reach.

**Result (full stack vs the real baseline, 10 runs per size, 0 collisions and 0 timeouts for the full stack):**

| Fleet | Full stack | Baseline | Gain |
|---|---|---|---|
| 3 AMRs (11×15) | 204.9 ± 8.1 | 417.7 ± 130.3 | **+50.9%** |
| 5 AMRs (11×21) | 263.5 ± 24.5 | 832.0 ± 461.8 | +68.3% (baseline timed out 1/10) |
| 10 AMRs (19×36) | 474.6 ± 28.6 | 1064.2 ± 167.6 | **+55.4%** |

**The most uncomfortable finding, kept on the record:** measured against a baseline that actually finishes, **the old Part 1 negotiation stack is roughly equal to stop-and-wait — not faster.** Every bit of the gain above comes from the Part 2 layers.

**Still open:** 20+ AMRs are not benchmarked (`layout_for_fleet(20)` gives a 31×63 floor, never run); Session 7 still lacks a congestion-level axis and 30 runs per size; live logs have no wall-clock timestamps, so 3 cases of a robot entering a cell another had left one tick earlier could not be *proven* sub-tick safe from logs alone.

**Simulate it:** `python -m sim.bench_matrix` and `python -m sim.fast_sim --robots 4 --tasks 24 --trials 5 --full`

---

## Scoreboard (demo map, 4 robots, 24 tasks, 5 trials, baseline negotiation = 537.6 ticks)

| Layer | Decision | Result | Confidence |
|---|---|---|---|
| L4 | C2 local PIBT | **217.0 ticks (+59.6%)**, wait 865 → 6 | Strong — largest single win |
| L3 | C3 local wait-for graph | 335.8 (+37.5%), deadlock recovery 19 → 1 tick | Strong |
| L5 | C4 congestion routing | 339.6 (+36.8%) | Strong |
| L5 | C5 D\* Lite | 407.8 (+24.1%) fleet; replan 13% faster *directed only* | Mixed — slower undirected |
| L5 | C1 directed graph | 420.6 (+21.8%), aisle head-ons 532 → 0 | Strong |
| L6 | C6 Hungarian batching | 498.8 (+7.2%); allocation quality real, fleet gain within noise | Weak on this workload |
| L1 | Perception | Qualitative — unmapped obstacles now detected at all | Works after the audit fix |
| L2 | Occupancy shield + race rule | **0 collisions in every configuration** | Exact in sim; async radio needs L1 backstop |

Every figure here is post-audit. Where a number did not survive re-measurement, the corrected one is what appears — see case 18.

---

## 21. Where an Idle Robot Should Stand

**The Scenario:**
Watching the live fleet between jobs: the robots spawn in a neat line across the bottom staging
row, then immediately scatter to the four corners of the floor and sit there. On a screen
recording it reads as random drift with no cause — and every new job starts with a long trip back
in from a corner.

**The Problem:**
The parking policy from case 19 said "idle robots go to the nearest perimeter lane cell". That
solved the real bug (idle robots camping around dropoff D(10,8) and walling it off) but it is a
*relative* rule: it depends on where the robot happens to finish, so the resting formation is
different every time and robots migrate across the floor between jobs.

The obvious fix — "just stay where you are" — does not work. Measured: idle robots settling on
arbitrary cells in the open staging rows sends the 4-robot / 24-task run from **212 → 731 ticks
with 2/5 runs timing out**. Idle robots in the middle of the traffic are genuinely expensive.

**The Solution:**
Each robot gets a fixed **home cell** and returns to it. Home is its spawn cell, unless that cell
is one an idle robot may not occupy — a pickup/dropoff/charger, the approach square to one, or a
single-width aisle — in which case it is the nearest cell that qualifies (`_is_out_of_the_way()`).
If a peer is sitting on its home, it settles on the nearest clear cell instead.

The home line itself was then chosen so no robot has to be relocated at all:
`START_POSITIONS = [(9,3), (9,5), (9,9), (9,11), (0,0), (0,13)]` — four across the bottom staging
row, clear of the dropoffs at (10,2)/(10,8) and their approach squares, then the top corridor.

**Result** (4 robots, 24 tasks, 5 trials, full stack):

| parking policy | avg ticks | timeouts | collisions |
|---|---|---|---|
| nearest perimeter lane (case 19) | 211.2 | 0 | 0 |
| stay wherever you finish | 731.2 | **2/5** | 0 |
| fixed home cell (this) | **212.0** | 0 | 0 |

Identical performance to the perimeter policy, and the fleet holds a readable formation: verified
over 60 idle ticks, all five robots sit exactly on their home cells and never move.

**Caveat:** home cells are per-map. `build_warehouse()` floors larger than the demo map fall back
to `_pick_home()` picking the nearest qualifying cell to each spawn, which is correct but not
necessarily tidy.
