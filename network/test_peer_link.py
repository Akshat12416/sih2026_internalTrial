"""Regression check: a robot that broadcasts before its peers are up must not go deaf.
On Windows that first sendto() makes the next recv raise ConnectionResetError.
Run: python -m network.test_peer_link"""
import time

from network import peer_link

peer_link.BASE_PORT = 9800  # stay clear of a running fleet (9500+)
got = []
r1 = peer_link.UDPPeerLink("R1", 0, [0, 1], got.append)
r1.start()
r1.broadcast({"type": "intent", "robot_id": "R1"})  # R2 not listening yet
time.sleep(0.5)
r2 = peer_link.UDPPeerLink("R2", 1, [0, 1], lambda m: None)
r2.start()
for _ in range(5):
    r2.broadcast({"type": "task_announce", "robot_id": "R2"})
    time.sleep(0.1)
time.sleep(0.5)
r1.stop(); r2.stop()
assert r1._rx_thread is not None and got, "R1 went deaf after sending to a closed port"
print(f"PASS: R1 received {len(got)} messages")
