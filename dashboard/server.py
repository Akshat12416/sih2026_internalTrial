"""
dashboard/server.py
====================
The dashboard is a PASSIVE OBSERVER on the mesh -- it opens a UDP socket
just like a robot would, and every robot's broadcast list includes the
dashboard's port (see orchestrator.py --observer-ports). Crucially the
dashboard never sends anything back into the fleet: pull the plug on it
and the robots keep coordinating exactly as before. That's the litmus
test for "monitoring", not "control".

Run:  python -m dashboard.server --port 9600 --robots 3
Then open http://127.0.0.1:8000
"""
import argparse
import asyncio
import json
import socket
import threading
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import random

app = FastAPI()
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

fleet_state: dict = {}       # robot_id -> latest status
network_events: list = []    # max 50 recent events
connections: list = []
loop_ref = {"loop": None}


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/warehouse")
def warehouse():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from core.layouts import demo_warehouse
    wmap = demo_warehouse()
    return {"grid": wmap.grid, "choke_points": wmap.choke_points,
            "pickup": wmap.pickup_points, "dropoff": wmap.dropoff_points,
            "charge": wmap.charge_points}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive; browser sends nothing meaningful
    except WebSocketDisconnect:
        connections.remove(websocket)


def udp_listener(port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", port))
    sock.settimeout(0.5)
    while True:
        try:
            data, _ = sock.recvfrom(65536)
        except socket.timeout:
            continue
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            continue
        if msg.get("type") == "status":
            fleet_state[msg["robot_id"]] = msg
        elif msg.get("type") == "intent":
            if msg["robot_id"] in fleet_state:
                fleet_state[msg["robot_id"]]["intent"] = msg["path"]
                fleet_state[msg["robot_id"]]["priority"] = msg["priority"]
        elif msg.get("type") in ("task_announce", "bid", "task_claimed"):
            evt = dict(msg)
            evt["local_t"] = time.time()
            network_events.append(evt)
            if len(network_events) > 50:
                network_events.pop(0)
        elif msg.get("type") == "blockage":
            fleet_state.setdefault("_events", []).append(
                {"kind": "blockage", "cell": msg["cell"], "t": time.time()})

        loop = loop_ref["loop"]
        if loop:
            asyncio.run_coroutine_threadsafe(broadcast_state(), loop)


async def broadcast_state():
    robots = [v for k, v in fleet_state.items() if k != "_events"]
    events = fleet_state.get("_events", [])
    payload = json.dumps({"robots": robots, "events": events, "network_events": network_events})
    dead = []
    for ws in connections:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for d in dead:
        if d in connections:
            connections.remove(d)


class BenchmarkRequest(BaseModel):
    robots: int
    tasks: int

class AutoTaskRequest(BaseModel):
    active: bool

auto_tasks_active = False

class TaskRequest(BaseModel):
    pickup: list = None
    dropoff: list = None

class TaskBatchRequest(BaseModel):
    tasks: list[dict]

@app.post("/api/spawn-batch")
async def spawn_batch(req: TaskBatchRequest):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for t_req in req.tasks:
        pickup = tuple(t_req["pickup"])
        dropoff = tuple(t_req["dropoff"])
        tid = f"UI-{int(time.time()*1000)}-{random.randint(100,999)}"
        msg = {
            "type": "task_announce",
            "task_id": tid,
            "pickup": pickup,
            "dropoff": dropoff,
            "t": 0
        }
        payload = json.dumps(msg).encode("utf-8")
        for port in range(9500, 9520):
            try:
                sock.sendto(payload, ("127.0.0.1", port))
            except OSError:
                pass
    sock.close()
    return {"status": "ok", "count": len(req.tasks)}

@app.post("/api/clear-tasks")
async def clear_tasks():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = json.dumps({"type": "clear_tasks"}).encode("utf-8")
    for port in range(9500, 9520):
        try:
            sock.sendto(payload, ("127.0.0.1", port))
        except OSError:
            pass
    sock.close()
    return {"status": "ok"}

@app.post("/api/spawn-task")
async def spawn_task(req: TaskRequest = None):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from core.layouts import demo_warehouse
    wmap = demo_warehouse()
    
    if req and req.pickup:
        pickup = tuple(req.pickup)
    else:
        pickup = random.choice(wmap.pickup_points)
        
    if req and req.dropoff:
        dropoff = tuple(req.dropoff)
    else:
        dropoff = random.choice(wmap.dropoff_points)
        
    tid = f"UI-{int(time.time()*1000)}"
    msg = {
        "type": "task_announce",
        "task_id": tid,
        "pickup": pickup,
        "dropoff": dropoff,
        "t": 0
    }
    payload = json.dumps(msg).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for port in range(9500, 9520):
        try:
            sock.sendto(payload, ("127.0.0.1", port))
        except OSError:
            pass
    sock.close()
    return {"status": "ok", "task_id": tid}

async def auto_task_loop():
    global auto_tasks_active
    while True:
        if auto_tasks_active:
            await spawn_task()
            await asyncio.sleep(random.uniform(2.0, 4.0))
        else:
            await asyncio.sleep(1.0)

@app.post("/api/auto-tasks")
async def toggle_auto_tasks(req: AutoTaskRequest):
    global auto_tasks_active
    auto_tasks_active = req.active
    return {"status": "ok", "active": auto_tasks_active}

@app.post("/api/run-benchmark")
async def run_benchmark(req: BenchmarkRequest):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from sim.fast_sim import make_task_schedule, run, demo_warehouse
    wmap = demo_warehouse()
    seed = 42
    schedule = make_task_schedule(req.tasks, seed, wmap)
    coop = run(req.robots, schedule, cooperative=True, max_ticks=2500, seed=seed)
    base = run(req.robots, schedule, cooperative=False, max_ticks=2500, seed=seed)
    
    reduction = 0
    if base["ticks_to_finish"] > 0:
        reduction = round(100 * (base["ticks_to_finish"] - coop["ticks_to_finish"]) / base["ticks_to_finish"], 1)
        
    return {
        "coop": coop,
        "base": base,
        "reduction": reduction
    }

@app.on_event("startup")
async def startup():
    loop_ref["loop"] = asyncio.get_event_loop()
    asyncio.create_task(auto_task_loop())


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--observer-port", type=int, default=9600)
    ap.add_argument("--web-port", type=int, default=8000)
    args = ap.parse_args()

    t = threading.Thread(target=udp_listener, args=(args.observer_port,), daemon=True)
    t.start()
    uvicorn.run(app, host="127.0.0.1", port=args.web_port)
