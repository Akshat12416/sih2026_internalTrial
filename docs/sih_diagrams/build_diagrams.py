"""
Generates the SIH PPT diagrams as Excalidraw scenes (open excalidraw.com ->
Menu -> Open, or drag the .excalidraw file onto the canvas).

Run:  python docs/sih_diagrams/build_diagrams.py [--preview DIR]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from excal import Scene  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
TITLE = "Edge-AI Distributed Fleet Coordination for AMRs"


# =============================================================================
# 01  SOLUTION APPROACH
# =============================================================================
def solution_approach():
    s = Scene("Solution Approach — every AMR is its own edge brain",
              f"{TITLE} · no central server in the control loop")
    s.box("prob", 250, 330, 360, 300,
          "THE PROBLEM\n\n• Central cloud planner → latency\n• Wi-Fi dead zones → robots stall\n"
          "• Single point of failure\n• Head-on deadlocks at 1-wide aisles\n• Stop-and-wait wastes fleet time",
          "red", fs=17, align="left")
    s.box("sol", 900, 330, 720, 300,
          "OUR SOLUTION\n\nEach AMR runs the complete coordination stack on an onboard "
          "NVIDIA Jetson Orin Nano. Robots share position & intent peer-to-peer, bid for "
          "tasks in an open auction, plan their own routes and resolve conflicts locally in a "
          "single 250 ms tick. The dashboard only observes — unplug it and the fleet keeps working.",
          "blue", fs=19)
    s.arrow("prob", "sol", "solved by", color="#c92a2a")
    s.box("rule", 1590, 330, 420, 300,
          "DESIGN RULE\n\nAI recommends:\nperception · routing cost · task bids\n\n"
          "Deterministic layers decide & veto:\nPIBT · wait-for graph · L2 safety shield\n\n"
          "→ no model or network message can bypass the safety shield",
          "violet", fs=17)
    s.arrow("sol", "rule", "guarded by", color="#6741d9")

    cols = [(290, "PS 1 · Decentralized Communication", "teal",
             "• UDP peer-to-peer mesh (Wi-Fi 802.11s)\n• intent · bid · claim · blockage · heartbeat\n"
             "• gossip relay (TTL) across dead zones\n• HMAC-signed JSON messages\n• stale peers pruned after 3 s"),
            (740, "PS 2 · Conflict Resolution & Deadlocks", "orange",
             "• one-way aisles → no head-on conflicts\n• local PIBT resolves a conflict in 1 tick\n"
             "• wait-for graph breaks deadlock cycles\n• L2 shield: final collision veto\n• agreement via broadcast rank"),
            (1190, "PS 3 · Task Allocation & Re-routing", "yellow",
             "• Contract-Net auction + Hungarian batching\n• A* on directed graph + congestion cost\n"
             "• D* Lite incremental re-plan\n• YOLOv8-nano detects blocked aisles\n• unreachable task → re-auctioned"),
            (1640, "Fleet Dashboard (Expected Solution)", "green",
             "• FastAPI + WebSocket live stream\n• Three.js 3D digital twin + 2D map\n"
             "• positions · battery · intents · KPIs\n• read-only observer on the mesh\n• supervisory E-stop only")]
    for i, (cx, head, color, body) in enumerate(cols):
        s.box(f"h{i}", cx, 590, 420, 64, head, color, fs=18, sw=3)
        s.box(f"p{i}", cx, 750, 420, 230, body, color, fs=16, align="left")
        s.arrow(f"h{i}", f"p{i}", sides=("b", "t"))
        s.arrow("sol", f"h{i}", sides=("b", "t"), at=(0.08 + 0.28 * i, 0.5))

    s.box("out", 965, 1010, 1770, 150,
          "OUTCOME — measured on our working prototype (seeded simulation + 3 live robot processes over UDP)\n"
          "0 inter-robot collisions in every run   ·   51–68 % faster task completion than stop-and-wait (3, 5, 10 AMRs)   ·   "
          "head-on conflict 37 → 9 ticks   ·   deadlock recovery 19 → 1 tick   ·   fleet waiting time −98 %",
          "green", fs=19, sw=3)
    for i, (cx, *_rest) in enumerate(cols):
        s.arrow(f"p{i}", "out", sides=("b", "t"), at=(0.5, (cx - 80) / 1770))
    return s


# =============================================================================
# 02  SYSTEM ARCHITECTURE
# =============================================================================
LAYERS = [
    ("L7 · Observability", "status + intent telemetry to dashboard · KPI counters · event log", "Deterministic", "grey"),
    ("L6 · Task Allocation", "Contract-Net auction · Hungarian batch matching · ETA + battery-aware bids", "AI", "violet"),
    ("L5 · Global Routing", "A* on one-way guidance graph · D* Lite re-plan · congestion heat-map cost", "AI", "violet"),
    ("L4 · Multi-Agent Coordination", "local PIBT (priority inheritance + backtracking) over peers within 4 cells", "Deterministic", "blue"),
    ("L3 · Reservation & Deadlock", "ReservationBook of peer intents · wait-for-graph cycle detection · victim yields", "Deterministic", "blue"),
    ("L2 · Motion & Safety Shield", "occupancy veto · rank-based race rule · velocity smoothing · FINAL VETO", "Deterministic", "red"),
    ("L1 · Perception & World Model", "YOLOv8-nano (TensorRT) blocked-aisle detection · LiDAR occupancy · AprilTag + odometry EKF", "AI", "violet"),
    ("L0 · Communication Fabric", "UDP P2P mesh · gossip relay (TTL) for dead zones · heartbeat · HMAC-signed JSON", "Deterministic", "teal"),
]


def system_architecture():
    s = Scene("System Architecture — identical decentralized stack on every AMR",
              "Each layer has one job · AI layers recommend, deterministic layers decide · the dashboard only listens")
    s.label_box("node", 430, 130, 900, 990, "AMR Edge Node  (NVIDIA Jetson Orin Nano / Raspberry Pi 5)", "white", fs=22, ss="solid")
    y0 = 225
    for i, (name, algo, kind, color) in enumerate(LAYERS):
        cy = y0 + i * 110
        s.box(f"n{i}", 575, cy, 270, 90, name, color, fs=18, sw=3)
        s.box(f"a{i}", 945, cy, 440, 90, algo, color, fs=16)
        s.box(f"k{i}", 1245, cy, 130, 56, kind, "violet" if kind == "AI" else "grey", fs=15)
        if i:
            s.arrow(f"n{i-1}", f"n{i}", sides=("b", "t"))
    s.box("sens", 210, y0 + 6 * 110, 300, 110,
          "Onboard sensors\n2D LiDAR · RGB camera · wheel encoders + IMU · battery monitor (INA219)", "orange", fs=15)
    s.arrow("sens", "n6", "frames, scans, odometry")
    s.box("motor", 210, y0 + 5 * 110, 300, 90, "Motor controller (ESP32) → drive wheels", "orange", fs=16)
    s.arrow("n5", "motor", "approved velocity")
    s.box("legend", 210, 330, 300, 200,
          "LEGEND\n\nViolet = AI recommends\nBlue / Red = deterministic decides\nTeal = network fabric\n\n"
          "Decisions flow top → down;\nL2 always has the last word",
          "white", fs=15, align="left")

    s.box("mesh", 1590, 840, 300, 120, "Peer-to-Peer Mesh\nWi-Fi 802.11s · UDP JSON\nno central server", "teal", fs=17, sw=3)
    s.arrow("k7", "mesh", "broadcast / receive", sides=("r", "b"), at=(0.5, 0.25), both=True, color="#0c8599")
    s.box("peer2", 1990, 760, 280, 90, "AMR #2 — same stack", "blue", fs=17)
    s.box("peer3", 1990, 920, 280, 90, "AMR #3 … AMR #N", "blue", fs=17)
    s.arrow("mesh", "peer2", "intent · bid", sides=("r", "l"), at=(0.3, 0.5), both=True, color="#0c8599")
    s.arrow("mesh", "peer3", "blockage · heartbeat", sides=("r", "l"), at=(0.7, 0.5), both=True, color="#0c8599")
    s.box("dash", 1990, 380, 300, 170,
          "Fleet Dashboard\nFastAPI + WebSocket\nThree.js digital twin\npositions · battery · KPIs", "green", fs=17, sw=3)
    s.arrow("mesh", "dash", "status + intent (listen only)", sides=("t", "l"), at=(0.35, 0.35), color="#2f9e44", ss="dashed")
    s.arrow("dash", "mesh", "supervisory E-stop", sides=("l", "t"), at=(0.8, 0.75), color="#c92a2a", ss="dashed")
    s.box("wms", 1990, 1090, 300, 90, "Warehouse Management System (order feed)", "yellow", fs=16)
    s.arrow("wms", "mesh", "task_announce", sides=("l", "b"), at=(0.5, 0.75), color="#e67700")
    s.box("op", 1990, 190, 300, 70, "Warehouse operator (browser)", "white", fs=16)
    s.arrow("op", "dash", "monitor", sides=("b", "t"), both=True)
    return s


# =============================================================================
# 03  WORKFLOW — order to delivery, across all actors
# =============================================================================
def workflow():
    s = Scene("End-to-End Workflow — from pick order to delivery (no central controller)",
              "Swim-lanes show WHO does each step · every robot runs the same logic · numbers follow the order of events")
    lanes = [("Order Feed / WMS", "yellow"), ("All AMRs — Auction", "violet"), ("Winning AMR", "blue"),
             ("Peer AMRs", "teal"), ("Dashboard / Operator", "green")]
    L_Y, L_H, L_GAP = 120, 190, 14
    for i, (name, color) in enumerate(lanes):
        y = L_Y + i * (L_H + L_GAP)
        s.label_box(f"lane{i}", 30, y, 1830, L_H, "", color, ss="solid")
        s.box(f"ln{i}", 125, y + L_H / 2, 170, L_H - 30, name, color, fs=18, sw=3)
    cy = [L_Y + i * (L_H + L_GAP) + L_H / 2 for i in range(5)]
    X = [400, 700, 1000, 1300, 1600]
    W, H = 250, 110
    s.box("s1", X[0], cy[0], W, H, "1. New pick order (pickup, dropoff) arrives", "yellow", fs=16)
    s.box("s2", X[1], cy[0], W, H, "2. Broadcast task_announce to the mesh", "yellow", fs=16)
    s.box("s3", X[1], cy[1], W, H, "3. Each AMR bids: A* path cost + battery penalty", "violet", fs=16)
    s.box("s4", X[2], cy[1], W, H, "4. Bid window + batch pool (3-6 ticks)", "violet", fs=16)
    s.box("s5", X[3], cy[1], W, H, "5. Hungarian matching — identical result on every robot", "violet", fs=16)
    s.box("s6", X[4], cy[1], W, H, "6. Winner broadcasts task_claimed", "violet", fs=16)
    s.box("s7", X[4], cy[2], W, H, "7. Plan route: A* on one-way graph + congestion cost", "blue", fs=16)
    s.box("s8", X[3], cy[2], W, H + 20, "8. Every 250 ms: perceive → PIBT move → L2 shield → broadcast intent", "blue", fs=16)
    s.box("s9", X[2], cy[2], 230, 150, "9. Blocked aisle detected?", "yellow", fs=16, shape="diamond")
    s.box("s11", X[1], cy[2], W, H, "11. Reach pickup → carry to dropoff", "blue", fs=16)
    s.box("s12", X[0], cy[2], W, H + 20, "12. Task done → next queued task, else park; charge if battery < 20 %", "blue", fs=16)
    s.box("s10", X[2], cy[3], W, H + 20, "10. Blockage alert → all AMRs D* Lite re-plan; unreachable task re-auctioned", "teal", fs=16)
    s.box("s13", X[4], cy[3], W, H + 20, "Peers update ReservationBook → yield or get pushed (PIBT)", "teal", fs=16)
    s.box("s14", X[3], cy[4], W, H, "Live digital twin: positions, battery, intents, KPIs", "green", fs=16)
    s.box("s15", X[0], cy[4], W, H, "Operator submits orders / E-stop", "green", fs=16)

    s.arrow("s1", "s2")
    s.arrow("s2", "s3", sides=("b", "t"))
    s.arrow("s3", "s4")
    s.arrow("s4", "s5")
    s.arrow("s5", "s6")
    s.arrow("s6", "s7", sides=("b", "t"))
    s.arrow("s7", "s8", sides=("l", "r"))
    s.arrow("s8", "s9", sides=("l", "r"))
    s.arrow("s9", "s11", "No", sides=("l", "r"))
    s.arrow("s11", "s12", sides=("l", "r"))
    s.arrow("s9", "s10", "Yes", sides=("b", "t"), color="#c92a2a")
    s.arrow("s10", "s8", "new path", sides=("r", "b"), at=(0.3, 0.25), color="#0c8599")
    s.arrow("s8", "s13", "intent {path, goal, rank}", sides=("b", "l"), at=(0.85, 0.5), both=True, color="#0c8599",
            label_pos=(1392, cy[2] + 132))
    s.arrow("s8", "s14", "status over UDP (listen-only)", sides=("b", "t"), color="#2f9e44", ss="dashed",
            label_pos=(1300, cy[3] + 62))
    s.arrow("s12", "s3", "free again → bid", sides=("t", "l"), color="#6741d9")
    s.arrow("s15", "s1", "orders", sides=("l", "l"), via=[(255, cy[4]), (255, cy[0])], color="#2f9e44")
    return s


# =============================================================================
# 04  FLOWCHART — per-tick control loop on each AMR
# =============================================================================
def flowchart():
    s = Scene("Flowchart — decision loop running on every AMR, every 250 ms",
              "Same code in simulation and on the robot · the L2 shield is the final gate before any wheel moves")
    A, B, RA, LA, RB = 560, 1500, 940, 180, 1880
    Y = 60
    s.box("start", A, 130 + Y, 320, 70, "START — tick begins", "green", fs=18, shape="ellipse", sw=3)
    s.box("p1", A, 250 + Y, 360, 90, "Receive peer messages → update ReservationBook, bids, blockages", "teal", fs=16)
    s.box("d1", A, 400 + Y, 260, 130, "First tick after boot?", "yellow", fs=16, shape="diamond")
    s.box("b1", RA, 400 + Y, 300, 90, "Broadcast hello (own position), wait for next tick", "teal", fs=16)
    s.box("p2", A, 560 + Y, 360, 90, "L1 Perception: YOLOv8-nano + LiDAR scan along the path", "violet", fs=16)
    s.box("d2", A, 715 + Y, 290, 150, "Obstacle confirmed in 2 frames?", "yellow", fs=16, shape="diamond")
    s.box("b2", RA, 715 + Y, 300, 100, "Mark map · broadcast blockage · D* Lite re-plan", "violet", fs=16)
    s.box("d3", A, 890 + Y, 260, 130, "Battery ≤ 20 %?", "yellow", fs=16, shape="diamond")
    s.box("b3", LA, 890 + Y, 280, 90, "Goal := nearest charging dock", "orange", fs=16)
    s.box("d4", A, 1055 + Y, 260, 130, "Reached current goal?", "yellow", fs=16, shape="diamond")
    s.box("b4", RA, 1055 + Y, 300, 100, "Advance task: pickup → dropoff → next task / park", "blue", fs=16)
    s.box("p3", A, 1210 + Y, 360, 90, "L6: bid on open tasks · settle auction (Hungarian)", "violet", fs=16)
    s.box("d5", A, 1360 + Y, 260, 130, "Valid path to goal?", "yellow", fs=16, shape="diamond")
    s.box("b5", RA, 1360 + Y, 300, 90, "L5: A* / D* Lite with congestion cost", "violet", fs=16)
    s.box("ca", A, 1500 + Y, 76, 76, "A", "dark", fs=22, shape="ellipse")

    s.arrow("start", "p1", sides=("b", "t"))
    s.arrow("p1", "d1", sides=("b", "t"))
    s.arrow("d1", "b1", "Yes", sides=("r", "l"))
    s.arrow("d1", "p2", "No", sides=("b", "t"))
    s.arrow("p2", "d2", sides=("b", "t"))
    s.arrow("d2", "b2", "Yes", sides=("r", "l"))
    s.arrow("d2", "d3", "No", sides=("b", "t"))
    s.arrow("b2", "d3", sides=("b", "r"))
    s.arrow("d3", "b3", "Yes", sides=("l", "r"))
    s.arrow("d3", "d4", "No", sides=("b", "t"))
    s.arrow("b3", "d4", sides=("b", "l"))
    s.arrow("d4", "b4", "Yes", sides=("r", "l"))
    s.arrow("d4", "p3", "No", sides=("b", "t"))
    s.arrow("b4", "p3", sides=("b", "r"))
    s.arrow("p3", "d5", sides=("b", "t"))
    s.arrow("d5", "b5", "No", sides=("r", "l"))
    s.arrow("d5", "ca", "Yes", sides=("b", "t"))
    s.arrow("b5", "ca", sides=("b", "r"))

    s.box("cb", B, 130 + Y, 76, 76, "A", "dark", fs=22, shape="ellipse")
    s.box("d6", B, 290 + Y, 320, 170, "In a wait-for cycle AND I am the chosen victim?", "yellow", fs=16, shape="diamond")
    s.box("b6", RB, 290 + Y, 300, 100, "L3: yield — blacklist contested cell, re-plan", "blue", fs=16)
    s.box("p4", B, 480 + Y, 380, 110,
          "L4 local PIBT with peers ≤ 4 cells → proposed next cell (held ≥ 2 ticks → request path cell)", "blue", fs=16)
    s.box("d8", B, 690 + Y, 340, 200, "L2 Safety Shield: cell free AND no higher-rank peer entering?", "red", fs=16, shape="diamond", sw=3)
    s.box("p5", B, 900 + Y, 340, 90, "Move one cell · update path · battery −0.35 %", "blue", fs=16)
    s.box("b8", RB, 690 + Y, 300, 90, "VETO: stay in place, wait counter + 1", "red", fs=16)
    s.box("p6", B, 1050 + Y, 380, 100, "Broadcast intent {path, goal, rank} + status to peers & dashboard", "teal", fs=16)
    s.box("end", B, 1190 + Y, 320, 70, "END — next tick", "green", fs=18, shape="ellipse", sw=3)

    s.arrow("cb", "d6", sides=("b", "t"))
    s.arrow("d6", "b6", "Yes", sides=("r", "l"))
    s.arrow("d6", "p4", "No", sides=("b", "t"))
    s.arrow("b6", "p4", sides=("b", "r"))
    s.arrow("p4", "d8", sides=("b", "t"))
    s.arrow("d8", "p5", "Safe", sides=("b", "t"), color="#2f9e44")
    s.arrow("d8", "b8", "Unsafe", sides=("r", "l"), color="#c92a2a")
    s.arrow("p5", "p6", sides=("b", "t"))
    s.arrow("b8", "p6", sides=("b", "r"))
    s.arrow("p6", "end", sides=("b", "t"))
    s.arrow("end", "start", "loop every 250 ms", sides=("l", "t"),
            via=[(1250, 1190 + Y), (1250, 110), (A, 110)], color="#495057", ss="dashed")
    s.box("legend", RB, 1150 + Y, 300, 190,
          "LEGEND\nGreen: start / end\nYellow: decision\nViolet: AI-assisted step\nBlue: coordination\n"
          "Red: safety gate\nTeal: communication", "white", fs=15, align="left")
    return s


# =============================================================================
# 05  USE CASE DIAGRAM
# =============================================================================
def use_case():
    s = Scene("Use Case Diagram — who interacts with the fleet system",
              "Human actors on the left · robot actors on the right · dashed arrows are «include» / «extend»")
    s.label_box("sys", 420, 120, 1080, 1100, "AMR Fleet Coordination System", "white", fs=22, ss="solid")
    L, R = 690, 1230
    left = ["Monitor live fleet: positions, battery, intents", "Receive alerts: blockage, low battery",
            "Submit / auto-generate pick orders", "View KPIs & run stop-and-wait benchmark",
            "Trigger E-stop / fleet reset", "Inject blocked aisle (test scenario)"]
    right = ["Share position & intent (P2P)", "Bid for & win tasks (auction)", "Plan / re-plan route (A*, D* Lite)",
             "Resolve choke-point conflicts (PIBT)", "Break deadlocks (wait-for graph)",
             "Detect blocked aisle (YOLOv8-nano)", "Enforce safety veto (L2 shield)", "Auto-charge on low battery",
             "Re-auction task if pickup unreachable"]
    for i, t in enumerate(left):
        s.box(f"L{i}", L, 220 + i * 150, 420, 90, t, "green", fs=16, shape="ellipse")
    for i, t in enumerate(right):
        s.box(f"R{i}", R, 200 + i * 112, 420, 84, t, "blue", fs=16, shape="ellipse")

    s.actor("op", 200, 330, "Warehouse Operator")
    s.actor("wms", 200, 600, "WMS / ERP")
    s.actor("eng", 200, 930, "Maintenance Engineer")
    s.actor("amr", 1720, 640, "AMR (edge robot)")
    s.actor("peer", 1720, 250, "Peer AMRs")
    for u in ("L0", "L1", "L2"):
        s.arrow("op", u, straight=True, head=False)
    s.arrow("wms", "L2", straight=True, head=False)
    for u in ("L3", "L4", "L5"):
        s.arrow("eng", u, straight=True, head=False)
    for i in range(len(right)):
        s.arrow("amr", f"R{i}", straight=True, head=False, color="#1971c2")
    for u in ("R0", "R1"):
        s.arrow("peer", u, straight=True, head=False, color="#0c8599")

    s.arrow("R2", "R1", "«include»", sides=("t", "b"), ss="dashed", color="#6741d9")
    s.arrow("R5", "R2", "«extend»", sides=("l", "l"), via=[(990, 760), (990, 424)], ss="dashed", color="#6741d9")
    s.arrow("L0", "R0", "«include»", sides=("r", "l"), ss="dashed", color="#2f9e44")
    s.arrow("L1", "R5", "«include»", sides=("r", "l"), via=[(955, 370), (955, 760)], ss="dashed", color="#2f9e44")
    return s


# =============================================================================
# 06  DATA FLOW DIAGRAM (Level 0 + Level 1)
# =============================================================================
def data_flow():
    s = Scene("Data Flow Diagram — Level 0 (context) and Level 1 (inside one AMR)",
              "Gane–Sarson style · rounded = process · grey bar = data store · square = external entity")
    s.text(40, 110, "LEVEL 0 — CONTEXT DIAGRAM", 22, "#6741d9")
    s.box("sys0", 1300, 300, 460, 150, "0 · AMR Fleet Coordination System\n(runs independently on every robot)", "violet", fs=19, sw=3)
    s.box("wms0", 500, 250, 280, 80, "WMS / Order feed", "yellow", fs=17, round_=False, sw=3)
    s.box("op0", 500, 350, 280, 80, "Warehouse Operator", "green", fs=17, round_=False, sw=3)
    s.box("peer0", 2100, 250, 280, 80, "Peer AMRs", "blue", fs=17, round_=False, sw=3)
    s.box("sens0", 2100, 350, 280, 80, "Sensors (camera, LiDAR, IMU, BMS)", "orange", fs=16, round_=False, sw=3)
    s.box("mot0", 1300, 500, 300, 60, "Drive motors", "orange", fs=17, round_=False, sw=3)
    s.arrow("wms0", "sys0", "pick orders", sides=("r", "l"), at=(0.5, 25 / 150))
    s.arrow("op0", "sys0", "orders · E-stop", sides=("r", "l"), at=(0.2, 111 / 150))
    s.arrow("sys0", "op0", "positions · battery · KPIs", sides=("l", "r"), at=(143 / 150, 0.8))
    s.arrow("peer0", "sys0", "intent · bid · claim · blockage · heartbeat", sides=("l", "r"), at=(0.5, 25 / 150), both=True)
    s.arrow("sens0", "sys0", "frames · scans · odometry · battery", sides=("l", "r"), at=(0.5, 125 / 150))
    s.arrow("sys0", "mot0", "velocity commands", sides=("b", "t"))

    s.text(40, 610, "LEVEL 1 — PROCESSES, DATA STORES AND FLOWS", 22, "#6741d9")

    def store(key, cx, cy, w, text):
        s.box(key, cx, cy, w, 60, text, "grey", fs=16, round_=False, sw=3)

    s.box("peer", 150, 800, 220, 80, "Peer AMRs", "blue", fs=17, round_=False, sw=3)
    s.box("wms", 150, 1060, 220, 80, "WMS / Order feed", "yellow", fs=17, round_=False, sw=3)
    s.box("op", 130, 1400, 200, 80, "Operator", "green", fs=17, round_=False, sw=3)
    s.box("mot", 2660, 1060, 200, 80, "Drive motors (ESP32)", "orange", fs=16, round_=False, sw=3)
    s.box("sens", 2960, 1300, 220, 90, "Camera · LiDAR · IMU · battery", "orange", fs=16, round_=False, sw=3)

    s.box("p1", 520, 960, 260, 110, "1.0 Communication Fabric\nUDP P2P · gossip · HMAC", "teal", fs=16)
    s.box("p3", 1300, 1060, 240, 110, "3.0 Task Allocation\nauction + Hungarian", "violet", fs=16)
    s.box("p4", 1640, 1060, 240, 110, "4.0 Route Planning\nA* / D* Lite + congestion", "violet", fs=16)
    s.box("p5", 1980, 1060, 240, 110, "5.0 Coordination\nlocal PIBT + wait-for graph", "blue", fs=16)
    s.box("p6", 2320, 1060, 240, 110, "6.0 L2 Safety Shield\nfinal veto", "red", fs=16, sw=3)
    s.box("p2", 2660, 1300, 240, 110, "2.0 Perception & Localization\nYOLOv8-nano · EKF", "violet", fs=16)
    s.box("p7", 470, 1400, 240, 110, "7.0 Telemetry & Dashboard feed", "green", fs=16)

    store("D2", 1550, 740, 1700, "D2 · ReservationBook — peer intents, ranks, current occupancy")
    store("D1", 960, 850, 300, "D1 · Warehouse Map")
    store("D3", 960, 1060, 300, "D3 · Task & Bid Registry")
    store("D4", 1250, 1300, 500, "D4 · Robot State — pose, battery, task")
    store("D5", 1640, 1480, 400, "D5 · Obstacle Map (dynamic blocks)")

    s.arrow("peer", "p1", "intent · bid · claim · blockage", sides=("r", "l"), at=(0.5, 0.3), both=True, color="#0c8599")
    s.arrow("wms", "p1", "task_announce", sides=("r", "l"), at=(0.5, 0.75), color="#e67700")
    s.arrow("p1", "D2", "peer intents", sides=("t", "l"), at=(0.3, 0.5))
    s.arrow("p1", "D1", "blockage alerts", sides=("t", "l"), at=(0.75, 0.5))
    s.arrow("p1", "D3", "tasks · bids", sides=("r", "l"), at=(0.75, 0.5))
    s.arrow("p3", "p1", "bid · task_claimed", sides=("t", "r"), at=(0.5, 0.3), color="#6741d9")
    s.arrow("D3", "p3", "open tasks")
    s.arrow("D4", "p3", "position · battery", sides=("t", "b"), at=(0.1, 0.5))
    s.arrow("p3", "p4", "assigned goal")
    s.arrow("D1", "p4", "one-way graph", sides=("r", "t"), at=(0.5, 0.2))
    s.arrow("D2", "p4", "congestion heat-map", sides=("b", "t"), at=((1640 - 700) / 1700, 0.5))
    s.arrow("D5", "p4", "obstacles", sides=("t", "b"))
    s.arrow("p4", "p5", "planned path")
    s.arrow("D2", "p5", "neighbour intents · ranks", sides=("b", "t"), at=((1980 - 700) / 1700, 0.5))
    s.arrow("p5", "p6", "proposed next cell")
    s.arrow("D2", "p6", "occupancy · ranks", sides=("b", "t"), at=((2320 - 700) / 1700, 0.5))
    s.arrow("p6", "mot", "approved move / stop", color="#c92a2a")
    s.arrow("sens", "p2", "raw sensor data", color="#d9480f")
    s.arrow("p2", "D5", "confirmed obstacles", sides=("b", "r"), at=(0.3, 0.5))
    s.arrow("p2", "D4", "pose · battery", sides=("b", "b"), at=(0.7, 0.5), via=[(2708, 1580), (1250, 1580)])
    s.arrow("D4", "p7", "state snapshot", sides=("l", "r"), at=(0.5, 0.0))
    s.arrow("p7", "p1", "intent + status broadcast", sides=("t", "b"), at=(0.5, 0.2), color="#0c8599")
    s.arrow("op", "p7", "orders · E-stop", sides=("r", "l"), at=(0.3, 0.3))
    s.arrow("p7", "op", "live twin · KPIs", sides=("l", "r"), at=(0.7, 0.7))
    return s


# =============================================================================
# 07  P2P PROTOCOL — sequence diagram
# =============================================================================
def protocol_sequence():
    s = Scene("P2P Communication Protocol — message sequence (no server in the loop)",
              "UDP JSON datagrams on the mesh · every robot keeps its own ReservationBook · dashboard only listens")
    names = [("WMS / Order feed", "yellow"), ("AMR R1", "blue"), ("AMR R2", "blue"), ("AMR R3", "blue"), ("Dashboard", "green")]
    X = [230, 650, 1070, 1490, 1910]
    TOP, BOT = 160, 1640
    for i, ((n, c), x) in enumerate(zip(names, X)):
        s.box(f"h{i}", x, TOP, 260, 70, n, c, fs=19, sw=3)
        s.line([(x, TOP + 35), (x, BOT)], "#868e96", ss="dashed")
        s.box(f"f{i}", x, BOT + 30, 260, 50, n, c, fs=16)

    def msg(y, a, b, text, color="#1e1e1e", ss="solid", both=False):
        s.free_arrow([(X[a], y), (X[b], y)], text, color=color, ss=ss, both=both, fs=15)

    def note(key, y, a, b, text, color="yellow", h=60):
        x0, x1 = min(X[a], X[b]) - 120, max(X[a], X[b]) + 120
        s.box(key, (x0 + x1) / 2, y, x1 - x0, h, text, color, fs=15)

    def phase(y, text):
        s.box(f"ph{y}", 1070, y, 2000, 40, text, "dark", fs=17)

    y = 250
    phase(y, "1 · TASK AUCTION (Contract-Net + Hungarian batch)")
    msg(y + 60, 0, 1, "task_announce {T7, pickup, dropoff}", "#e67700")
    msg(y + 100, 0, 2, "task_announce (same broadcast)", "#e67700")
    msg(y + 140, 0, 3, "task_announce (same broadcast)", "#e67700")
    msg(y + 190, 1, 2, "bid {T7, cost 14}", "#6741d9", both=True)
    msg(y + 230, 2, 3, "bid {T7, cost 9}", "#6741d9", both=True)
    note("n1", y + 295, 1, 3, "After the bid window every robot runs the SAME Hungarian matching on the SAME bids → all agree: R2 wins")
    msg(y + 360, 2, 1, "task_claimed {T7, winner R2}", "#6741d9")
    msg(y + 360, 2, 3, "task_claimed", "#6741d9")

    y = 680
    phase(y, "2 · MOTION & CONFLICT RESOLUTION (every 250 ms)")
    msg(y + 60, 2, 1, "intent {path[6], goal, rank}", "#0c8599")
    msg(y + 100, 1, 2, "intent {path[6], goal, rank}", "#0c8599")
    note("n2", y + 170, 1, 2, "Head-on at a choke point → each runs local PIBT on the same broadcasts: lower rank R1 side-steps in one tick · L2 shield confirms the cell is free", "orange", 80)
    msg(y + 240, 1, 2, "intent (side-step)", "#0c8599")
    msg(y + 240, 2, 3, "intent (passes)", "#0c8599")

    y = 990
    phase(y, "3 · BLOCKED AISLE → RE-ROUTING")
    note("n3", y + 60, 3, 3, "YOLOv8-nano confirms pallet at (3,7)", "violet")
    msg(y + 120, 3, 2, "blockage {cell (3,7), ttl 30 s}", "#c92a2a")
    msg(y + 160, 2, 1, "gossip relay (R1 out of R3's radio range)", "#c92a2a", ss="dashed")
    note("n4", y + 225, 1, 2, "D* Lite repairs only the affected part of the route · task re-auctioned if its pickup becomes unreachable", "blue")

    y = 1300
    phase(y, "4 · TELEMETRY & SUPERVISION")
    msg(y + 60, 1, 4, "status {pos, battery, state} + intent", "#2f9e44", ss="dashed")
    msg(y + 100, 2, 4, "status + intent", "#2f9e44", ss="dashed")
    msg(y + 140, 3, 4, "status + intent", "#2f9e44", ss="dashed")
    msg(y + 200, 4, 1, "E-stop (supervisory, signed) — the only message the dashboard may send", "#c92a2a", ss="dashed")
    note("n5", y + 270, 1, 3, "Heartbeat every tick · a peer silent for 3 s is pruned from every ReservationBook", "teal")
    return s


# =============================================================================
# 08  TECHNOLOGY STACK
# =============================================================================
def tech_stack():
    s = Scene("Technologies Used — hardware to dashboard",
              "Every block below is part of the integrated solution · lower layers serve the ones above")
    bands = [
        ("Fleet Dashboard & Ops", "green", ["FastAPI + Uvicorn", "WebSocket live stream", "Three.js 3D digital twin",
                                            "HTML5 Canvas 2D map", "REST: orders · reset · benchmark"]),
        ("Coordination Algorithms", "blue", ["Contract-Net + Hungarian (SciPy)", "A* on one-way graph", "D* Lite re-planning",
                                             "Congestion heat-map", "PIBT + wait-for graph", "L2 safety shield"]),
        ("Onboard AI & Software", "violet", ["Python 3.12 · NumPy", "YOLOv8-nano + TensorRT INT8", "OpenCV",
                                             "ROS 2 Humble drivers", "AprilTag + odometry EKF"]),
        ("P2P Networking", "teal", ["UDP sockets · JSON", "Wi-Fi 802.11s mesh", "Gossip relay (TTL)",
                                    "HMAC-SHA256 signing", "Heartbeat + 3 s pruning"]),
        ("Edge Hardware (per AMR)", "orange", ["NVIDIA Jetson Orin Nano", "Raspberry Pi 5 (low-cost)", "RPLIDAR A1 2D LiDAR",
                                               "RGB camera · IMU · encoders", "ESP32 motor driver", "Li-ion + INA219 BMS"]),
    ]
    Y0, BH, GAP = 140, 150, 26
    for i, (name, color, chips) in enumerate(bands):
        y = Y0 + i * (BH + GAP)
        s.label_box(f"band{i}", 30, y, 2090, BH, "", color, ss="solid")
        s.box(f"bn{i}", 180, y + BH / 2, 270, BH - 30, name, color, fs=20, sw=3)
        for j, chip in enumerate(chips):
            s.box(f"c{i}{j}", 450 + j * 300, y + BH / 2, 270, 70, chip, "white", fs=16)
        if i:
            s.arrow(f"bn{i}", f"bn{i-1}", sides=("t", "b"))
    y = Y0 + 5 * (BH + GAP)
    s.label_box("val", 30, y, 2090, BH, "", "grey", ss="solid")
    s.box("valn", 180, y + BH / 2, 270, BH - 30, "Simulation & Validation", "grey", fs=20, sw=3)
    for j, chip in enumerate(["Deterministic fleet simulator (same code)", "1 OS process = 1 robot live demo",
                              "Stop-and-wait baseline benchmark", "Seeded multi-trial matrix (3–10 AMRs)",
                              "Gazebo hardware-in-the-loop", "Git · pytest-style regression checks"]):
        s.box(f"v{j}", 450 + j * 300, y + BH / 2, 270, 70, chip, "white", fs=15)
    s.arrow("valn", "bn4", "validates", sides=("t", "b"))
    return s


# =============================================================================
# 09  METHODOLOGY & RESULTS
# =============================================================================
def methodology():
    s = Scene("Methodology & Implementation — how we build and prove it",
              "Iterative: each layer is added behind a feature flag, benchmarked against the previous version, then kept")
    phases = [("1 · Model", "warehouse grid, choke points, one-way aisles, task generator", "grey"),
              ("2 · Communicate", "UDP P2P mesh, intent / bid / claim / blockage messages", "teal"),
              ("3 · Allocate", "Contract-Net auction, Hungarian batching, battery-aware bids", "violet"),
              ("4 · Route", "A* + congestion cost, D* Lite re-plan, YOLOv8-nano obstacles", "violet"),
              ("5 · Coordinate", "local PIBT, wait-for graph, L2 safety shield", "blue"),
              ("6 · Observe", "FastAPI + WebSocket dashboard, 3D digital twin, KPIs", "green"),
              ("7 · Validate & Deploy", "stop-and-wait benchmark, 3-10 AMR matrix, Jetson AMRs", "orange")]
    for i, (head, body, color) in enumerate(phases):
        cx = 170 + i * 285
        s.box(f"ph{i}", cx, 190, 250, 70, head, color, fs=19, sw=3)
        s.box(f"pb{i}", cx, 310, 250, 130, body, color, fs=15)
        s.arrow(f"ph{i}", f"pb{i}", sides=("b", "t"))
        if i:
            s.arrow(f"ph{i-1}", f"ph{i}")
    s.box("loop", 1025, 440, 1960, 50,
          "Per layer: implement behind flag → unit / scenario test → fleet benchmark (seeded) → keep only if faster AND still 0 collisions",
          "yellow", fs=17)
    for i in range(7):
        s.arrow(f"pb{i}", "loop", sides=("b", "t"), at=(0.5, (170 + i * 285 - 45) / 1960))

    s.text(60, 520, "RESULTS — total task-completion time (ticks, lower is better; 10 seeded runs each)", 22, "#1e1e1e")
    base_y, scale = 1100, 0.45
    data = [("3 AMRs", 417.7, 204.9, "+51 %"), ("5 AMRs", 832.0, 263.5, "+68 %"), ("10 AMRs", 1064.2, 474.6, "+55 %")]
    s.line([(90, base_y), (1000, base_y)], "#495057", sw=2)
    for i, (label, b, f, gain) in enumerate(data):
        gx = 200 + i * 290
        hb, hf = b * scale, f * scale
        s.box(f"bb{i}", gx, base_y - hb / 2, 90, hb, "", "red", round_=False)
        s.box(f"bf{i}", gx + 100, base_y - hf / 2, 90, hf, "", "green", round_=False)
        s.text(gx, base_y - hb - 30, f"{b:.0f}", 17, "#c92a2a", align="center")
        s.text(gx + 100, base_y - hf - 30, f"{f:.0f}", 17, "#2f9e44", align="center")
        s.text(gx + 50, base_y + 12, label, 18, "#1e1e1e", align="center")
        s.text(gx + 50, base_y + 40, gain + " faster", 18, "#2f9e44", align="center")
    s.box("lg1", 170, 600, 40, 24, "", "red", round_=False)
    s.text(200, 590, "Stop-and-wait baseline", 16, "#c92a2a")
    s.box("lg2", 460, 600, 40, 24, "", "green", round_=False)
    s.text(490, 590, "Our decentralized stack", 16, "#2f9e44")

    kpis = [("0", "inter-robot collisions in every run", "green"),
            ("51–68 %", "faster than stop-and-wait (≥ 20 % required)", "green"),
            ("37 → 9", "ticks to clear a head-on conflict", "blue"),
            ("19 → 1", "ticks to break a 4-robot deadlock", "blue"),
            ("−98 %", "fleet waiting time", "teal"),
            ("3 processes", "independent robots over UDP in the live prototype", "violet")]
    for i, (big, small, color) in enumerate(kpis):
        cx, cy = 1270 + (i % 2) * 400, 650 + (i // 2) * 170
        s.box(f"k{i}", cx, cy, 370, 140, f"{big}\n{small}", color, fs=20, sw=3)
    return s


# =============================================================================
# 10  COLLISION-FREE BY DESIGN — defence in depth
# =============================================================================
def safety_pipeline():
    s = Scene("Zero Collisions by Design — five independent defence layers",
              "Each layer removes a class of conflict; whatever slips through is caught by the next · L2 always has the final word")
    stages = [("1 · STRUCTURE", "One-way aisles (directed graph)", "Head-on conflicts in 1-wide aisles become impossible", "532 → 0 aisle head-ons", "grey"),
              ("2 · PLANNING", "Space-time reservations + congestion cost", "Robots avoid cells peers already claimed", "wait time −69 %", "violet"),
              ("3 · COORDINATION", "Local PIBT (priority inheritance)", "Crossing / following conflicts resolved in one tick", "37 → 9 tick delay", "blue"),
              ("4 · DEADLOCK", "Wait-for graph + victim yield", "Circular waits detected instantly, one robot yields", "19 → 1 tick", "blue"),
              ("5 · SAFETY", "L2 shield: occupancy + rank veto", "No move into an occupied or contested cell — ever", "0 collisions", "red")]
    for i, (tag, what, why, metric, color) in enumerate(stages):
        cx = 220 + i * 400
        s.box(f"t{i}", cx, 190, 340, 60, tag, "dark", fs=19)
        s.box(f"w{i}", cx, 300, 340, 100, what, color, fs=18, sw=3)
        s.box(f"y{i}", cx, 430, 340, 100, why, "white", fs=16)
        s.box(f"m{i}", cx, 540, 340, 60, metric, "green", fs=18, sw=3)
        s.arrow(f"t{i}", f"w{i}", sides=("b", "t"))
        s.arrow(f"w{i}", f"y{i}", sides=("b", "t"))
        s.arrow(f"y{i}", f"m{i}", sides=("b", "t"))
        if i:
            s.arrow(f"w{i-1}", f"w{i}")
    s.box("result", 1020, 660, 1940, 60, "RESULT: 0 inter-robot collisions across every simulated and live run", "green", fs=22, sw=3)
    for i in range(5):
        s.arrow(f"m{i}", "result", sides=("b", "t"), at=(0.5, (220 + i * 400 - 50) / 1940))

    s.text(60, 760, "EXAMPLE — head-on at a single-width choke point (R1 has the higher rank)", 22, "#1e1e1e")
    steps = [("t = 0", "R1 (east-bound) and R2 (west-bound) meet; both broadcast intent", [(1, "R1", "blue"), (3, "R2", "orange")], False),
             ("t = 1", "Local PIBT: R1 keeps its path; R2 is pushed into the side bay", [(2, "R1", "blue")], True),
             ("t = 2", "L2 shield confirms the cell is free → R1 passes", [(3, "R1", "blue")], True),
             ("t = 3", "R2 rejoins and continues west — no stop-and-wait", [(4, "R1", "blue"), (3, "R2", "orange")], False)]
    for k, (tt, cap, robots, in_bay) in enumerate(steps):
        ox, oy = 80 + k * 490, 830
        s.text(ox, oy, tt, 20, "#1e1e1e")
        for c in range(5):
            s.box(f"g{k}{c}", ox + 45 + c * 80, oy + 90, 80, 80, "", "grey", round_=False, sw=1)
        s.box(f"bay{k}", ox + 45 + 3 * 80, oy + 170, 80, 80, "" if in_bay else "side bay", "white", fs=13, round_=False, sw=1)
        for c, name, color in robots:
            s.box(f"r{k}{name}", ox + 45 + c * 80, oy + 90, 62, 62, name, color, fs=16, shape="ellipse")
        if in_bay:
            s.box(f"rb{k}", ox + 45 + 3 * 80, oy + 170, 62, 62, "R2", "orange", fs=16, shape="ellipse")
        s.box(f"cap{k}", ox + 205, oy + 290, 440, 70, cap, "white", fs=16)
        if k:
            s.arrow(f"cap{k-1}", f"cap{k}")
    return s



if __name__ == "__main__":
    diagrams = {
        "01_solution_approach": solution_approach,
        "02_system_architecture": system_architecture,
        "03_workflow": workflow,
        "04_flowchart_robot_control_loop": flowchart,
        "05_use_case": use_case,
        "06_data_flow_diagram": data_flow,
        "07_p2p_protocol_sequence": protocol_sequence,
        "08_technology_stack": tech_stack,
        "09_methodology_and_results": methodology,
        "10_zero_collision_safety_layers": safety_pipeline,
    }
    prev = os.path.join(OUT, "png")
    os.makedirs(prev, exist_ok=True)
    for name, fn in diagrams.items():
        print(name)
        sc = fn()
        sc.save(os.path.join(OUT, name + ".excalidraw"))
        if prev:
            sc.preview(os.path.join(prev, name + ".png"))
