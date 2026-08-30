"""
live/orchestrator.py
=====================
This script does NOT coordinate the robots -- it only launches them as
independent OS processes (standing in for independent physical machines)
and starts the passive dashboard. Once running, all coordination happens
purely through the UDP messages the robot processes exchange with each
other; the orchestrator's job ends the moment the processes are spawned.

Run:
    python -m live.orchestrator --robots 3
Then open http://127.0.0.1:8000 in a browser.
Ctrl+C stops everything.
"""
import argparse
import subprocess
import sys
import time

OBSERVER_PORT = 9600
WEB_PORT = 8000

START_POSITIONS = [(9, 2), (9, 5), (9, 8), (9, 11), (0, 2), (0, 8)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--robots", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    n = args.robots
    peer_list = ",".join(str(i) for i in range(n))
    procs = []

    dash = subprocess.Popen([sys.executable, "-m", "dashboard.server",
                              "--observer-port", str(OBSERVER_PORT),
                              "--web-port", str(WEB_PORT)])
    procs.append(dash)
    time.sleep(1.0)
    print(f"Dashboard: http://127.0.0.1:{WEB_PORT}")

    for i in range(n):
        pos = START_POSITIONS[i % len(START_POSITIONS)]
        p = subprocess.Popen([
            sys.executable, "-m", "live.robot_process",
            "--id", f"R{i+1}", "--index", str(i), "--peers", peer_list,
            "--observer-ports", str(OBSERVER_PORT),
            "--pos", f"{pos[0]},{pos[1]}", "--seed", str(args.seed),
        ])
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
