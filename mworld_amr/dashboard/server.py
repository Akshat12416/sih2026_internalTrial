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

app = FastAPI()
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

fleet_state: dict = {}       # robot_id -> latest status
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
        elif msg.get("type") == "blockage":
            fleet_state.setdefault("_events", []).append(
                {"kind": "blockage", "cell": msg["cell"], "t": time.time()})

        loop = loop_ref["loop"]
        if loop:
            asyncio.run_coroutine_threadsafe(broadcast_state(), loop)


async def broadcast_state():
    payload = json.dumps({"robots": list(fleet_state.values())})
    dead = []
    for ws in connections:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for d in dead:
        if d in connections:
            connections.remove(d)


@app.on_event("startup")
async def startup():
    loop_ref["loop"] = asyncio.get_event_loop()


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--observer-port", type=int, default=9600)
    ap.add_argument("--web-port", type=int, default=8000)
    args = ap.parse_args()

    t = threading.Thread(target=udp_listener, args=(args.observer_port,), daemon=True)
    t.start()
    uvicorn.run(app, host="127.0.0.1", port=args.web_port)
