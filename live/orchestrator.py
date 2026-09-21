"""
live/orchestrator.py
=====================
This script does NOT coordinate the robots -- it only launches them as
independent OS processes (standing in for independent physical machines)
and starts the passive dashboard. Once running, all coordination happens
purely through the UDP messages the robot processes exchange with each
other; the orchestrator's job ends the moment the processes are spawned.

Run:
    python -m live.orchestrator --robots 3            # original negotiation
    python -m live.orchestrator --robots 3 --full     # full layered stack C1-C6
    python -m live.orchestrator --robots 3 --features pibt,wfg
Then open http://127.0.0.1:8000 in a browser.
Ctrl+C stops everything.
"""
import argparse
import os
import socket
import subprocess
import sys
import time

from core.layouts import demo_warehouse
from network.peer_link import BASE_PORT
from sim.fast_sim import start_positions

OBSERVER_PORT = 9600
WEB_PORT = 8000

# CLI feature name -> core/config.py flag (each robot process reads it from its env)
FEATURES = {"directed": "USE_DIRECTED_GRAPH", "pibt": "USE_PIBT", "wfg": "USE_WAITFOR_GRAPH",
            "congestion": "USE_CONGESTION_COST", "dstar": "USE_DSTAR_LITE", "batching": "USE_BATCHING"}


def _check_ports_free(web_port: int, observer_port: int, n_robots: int):
    """Fail loudly instead of leaving a half-started fleet behind. A dashboard
    already holding these ports silently swallows the new one, and the browser
    then shows an old process with no robots in it."""
    busy = []
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tcp.bind(("127.0.0.1", web_port))
    except OSError:
        busy.append(f"TCP {web_port} (dashboard web)")
    finally:
        tcp.close()
    for port, what in [(observer_port, "dashboard observer")] +                       [(BASE_PORT + i, f"robot R{i+1}") for i in range(n_robots)]:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.bind(("127.0.0.1", port))
        except OSError:
            busy.append(f"UDP {port} ({what})")
        finally:
            udp.close()
    if busy:
        print("Already in use: " + ", ".join(busy))
        print("Another dashboard or fleet is still running. Stop it first "
              "(close that terminal, or kill the python process holding the port), "
              "or run this one elsewhere: --web-port 8010 --observer-port 9610")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--robots", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--full", action="store_true", help="enable every layer (C1-C6)")
    ap.add_argument("--features", default="", help=f"comma separated subset of: {','.join(FEATURES)}")
    ap.add_argument("--web-port", type=int, default=WEB_PORT)
    ap.add_argument("--observer-port", type=int, default=OBSERVER_PORT)
    args = ap.parse_args()

    chosen = list(FEATURES) if args.full else [f for f in args.features.split(",") if f]
    unknown = [f for f in chosen if f not in FEATURES]
    if unknown:
        ap.error(f"unknown feature(s) {unknown}; choose from {list(FEATURES)}")
    env = dict(os.environ)
    for name, flag in FEATURES.items():
        env[flag] = "1" if name in chosen else "0"

    _check_ports_free(args.web_port, args.observer_port, args.robots)

    n = args.robots
    peer_list = ",".join(str(i) for i in range(n))
    procs = []

    dash = subprocess.Popen([sys.executable, "-m", "dashboard.server",
                              "--observer-port", str(args.observer_port),
                              "--web-port", str(args.web_port)], env=env)
    procs.append(dash)
    time.sleep(1.0)
    print(f"Dashboard: http://127.0.0.1:{args.web_port}")
    print(f"Layers enabled: {chosen or 'none (original negotiation)'}")

    for i, pos in enumerate(start_positions(n, demo_warehouse())):
        p = subprocess.Popen([
            sys.executable, "-m", "live.robot_process",
            "--id", f"R{i+1}", "--index", str(i), "--peers", peer_list,
            "--observer-ports", str(args.observer_port),
            "--pos", f"{pos[0]},{pos[1]}", "--seed", str(args.seed),
        ], env=env)
        procs.append(p)

    print(f"Launched {n} independent robot processes (PIDs: "
          f"{[p.pid for p in procs[1:]]}). Press Ctrl+C to stop the fleet.")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\nStopping fleet...")
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
