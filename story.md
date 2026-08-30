# Fleet Operations: The Journey of Decentralized Edge Coordination

This document chronicles the evolution of our decentralized robot swarm. As we built out the fleet, we encountered several complex edge cases that naturally arise when independent robots try to coordinate without a central server. 

Below is the chronological story of the problems we faced, the scenarios that exposed them, and the technical solutions we implemented to solve them.

---

## 1. The "Impatient Honking" Paralysis & Premature Yielding

**The Scenario:**
Robot 5 (R5) received a job but its path was blocked by Robot 3 (R3), which was sitting completely `IDLE`. R5 would ask R3 to move aside. R3 would agree and start moving. However, before R3 could fully get out of the way, R5 would recalculate its path, give up on the aisle entirely, and take a massive, battery-draining detour around the entire warehouse shelf. 

**The Problem:**
There were two issues here:
1. **Low Starvation Limit:** Active robots were too impatient. If their path was blocked, they would only wait a few ticks before giving up and recalculating a detour. 
2. **Honk Paralysis:** When the `IDLE` robot (R3) was trying to move out of the way, the active robot (R5) would continuously send "nudges" (honks) every tick. These continuous nudges were interrupting R3's escape plan, forcing it to freeze and recalculate constantly, trapping both robots.

**The Solution:**
- We increased the `STARVATION_WAIT_LIMIT` to 10 ticks, giving `IDLE` robots enough time to physically step out of the way before the active robot decides to detour.
- We implemented **Honk Ignoring**. When an `IDLE` robot is nudged, it finds a staging cell, generates an escape path, and enters a `MAKING WAY` state. While in this state, it strictly ignores any further nudges from impatient peers, allowing it to smoothly clear the aisle.

---

## 2. The Battery Dominance Flaw

**The Scenario:**
A new task popped up right next to R3. R3 was at 70% battery, which is plenty of power to finish the job. However, R5 was sitting across the warehouse at 95% battery. Because the auction system weighed battery levels strictly linearly, R5's extra 25% battery allowed it to outbid R3. R5 ended up driving all the way across the map to do R3's job, wasting massive amounts of time and overall fleet energy.

**The Problem:**
The battery penalty in the Contract Net Protocol auction was linear. A robot with 100% battery would always aggressively outbid a robot with 70% battery, regardless of how efficient the dispatch was. We needed a system where a 70% charged robot is considered "healthy enough" to win based on distance.

**The Solution:**
We implemented a **Non-Linear (Quadratic) Battery Penalty**. 
- If a robot has more than `60%` battery, its battery penalty is `0`. It competes purely on distance and efficiency.
- If a robot dips below `60%`, the penalty scales quadratically. This heavily suppresses low-battery robots from taking jobs, saving their power for charging trips, while letting all healthy robots compete strictly on spatial logic.

---

## 3. The Symmetric Livelock (Head-to-Head Standoff)

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

## 4. Inefficient Dispatching: The Need for Predictive Bidding

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

## 5. The "Split-Brain" Bidding Race Condition

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

## 6. The Auction Window Head-Start Discrepancy

**The Scenario:**
While monitoring the predictive bidding, we noticed an unfair advantage. When a task is announced, an `IDLE` robot sits completely still for the 3-tick auction window, waiting to see if it wins. But a busy robot doesn't pause—it keeps driving towards its dropoff during those 3 ticks!

**The Problem:**
Because the busy robot was actively making progress during the auction, its bid (calculated as "distance from now") was artificially high. By the time the 3-tick auction actually settled, the busy robot was physically 3 steps closer to its goal than its initial bid implied.

**The Solution:**
We applied an **Auction Window Discount**. When a busy robot calculates its predictive `ticks_to_finish`, we automatically subtract `AUCTION_WINDOW_TICKS` (3) from its cost. This perfectly aligns their bid with their true arrival time, giving them credit for the momentum they carry through the auction window.
