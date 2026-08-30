"""
live/robot_process.py
======================
This file is launched as a SEPARATE OS process per robot (see orchestrator.py).
That's intentional: separate processes cannot share Python memory, so the
only way robots can possibly coordinate is by actually sending each other
UDP packets over the loopback network -- exactly mirroring separate physical
machines on separate radios. If you deleted the networking and this still
worked, that would prove the sim was cheating by sharing memory. It isn't.

Run standalone for testing:
    python -m live.robot_process --id R1 --index 0 --peers 0,1,2 --pos 9,2
"""
import argparse
import json
import random
import sys
import time

sys.path.insert(0, ".")
from core.layouts import demo_warehouse
from core.robot_agent import RobotAgent, Task
from network.peer_link import UDPPeerLink

TICK_S = 0.35


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--peers", required=True, help="comma separated peer indices incl. self")
    ap.add_argument("--observer-ports", default="", help="comma separated extra UDP ports (e.g. dashboard)")
    ap.add_argument("--pos", required=True, help="row,col")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ticks", type=int, default=0, help="0 = run forever")
    ap.add_argument("--auto-tasks", action="store_true", help="Generate tasks automatically")
    args = ap.parse_args()

    random.seed(args.seed + args.index)
    wmap = demo_warehouse()
    start = tuple(int(x) for x in args.pos.split(","))
    peer_indices = [int(x) for x in args.peers.split(",")]

    agent_holder = {}

    def on_message(msg):
        agent = agent_holder.get("agent")
        if agent is not None:
            agent.on_message(msg)

    link = UDPPeerLink(args.id, args.index, peer_indices, on_message)
    if args.observer_ports:
        link.observer_ports = [int(p) for p in args.observer_ports.split(",")]

    agent = RobotAgent(robot_id=args.id, pos=start, wmap=wmap,
                        send=link.broadcast, priority_base=args.index)
    agent_holder["agent"] = agent
    link.start()

    print(f"[{args.id}] online at {start}, peers={peer_indices}", flush=True)

    tick = 0
    next_task_at = random.randint(3, 10)
    task_counter = 0
    try:
        while args.ticks == 0 or tick < args.ticks:
            tick += 1
            # Only ONE robot (index 0) plays the role of "order feed" so we
            # don't spam duplicate tasks -- this mimics a warehouse
            # management system dropping new pick orders into the fleet.
            # NOTE: index 0 only ANNOUNCES tasks, it does not assign them --
            # assignment still happens via decentralized auction below.
            if args.index == 0 and tick >= next_task_at and args.auto_tasks:
                task_counter += 1
                pickup = random.choice(wmap.pickup_points)
                dropoff = random.choice(wmap.dropoff_points)
                t = Task(f"T{args.index}-{task_counter}", pickup, dropoff, tick)
                agent.announce_task(t)
                next_task_at = tick + random.randint(6, 14)

            # random dynamic blockage injection, to test re-routing (rare)
            if random.random() < 0.003:
                cell = random.choice(wmap.pickup_points + wmap.dropoff_points)
                wmap.report_blockage(cell, duration_s=15)
                link.broadcast({"type": "blockage", "robot_id": args.id,
                                  "cell": cell, "duration": 15})

            agent.bid_on_open_tasks()
            agent.settle_auctions()
            agent.step()

            status = {"type": "status", "robot_id": args.id, "pos": agent.pos,
                        "battery": round(agent.battery, 1), "state": agent.state,
                        "completed": agent.completed_tasks, "t": tick}
            if agent.current_task:
                status["task_pickup"] = agent.current_task.pickup
                status["task_dropoff"] = agent.current_task.dropoff
            link.broadcast(status)
            print(f"[{args.id}] t={tick} pos={agent.pos} state={agent.state} "
                    f"batt={agent.battery:.0f}% done={agent.completed_tasks}", flush=True)
            time.sleep(TICK_S)
    except KeyboardInterrupt:
        pass
    finally:
        link.stop()


if __name__ == "__main__":
    main()
