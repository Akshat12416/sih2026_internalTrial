"""
network/peer_link.py
=====================
True peer-to-peer transport: every robot process opens its own UDP socket
and sends messages DIRECTLY to every other known peer's socket. There is no
broker, no server, no message queue in the middle. This mirrors how real
AMR fleets do it over 802.11 ad-hoc / Wi-Fi Direct / a mesh radio (e.g.
ESP-NOW, Zigbee, or DDS's peer discovery over multicast) -- the network
layer only moves bytes, it never makes a decision.

On real hardware you'd swap UDPPeerLink for an actual radio interface;
the rest of the codebase (core/*) would not change at all, which is the
point of keeping planning logic decoupled from transport.
"""
from __future__ import annotations
import json
import socket
import threading
import time
from typing import Callable, List

BASE_PORT = 9500


class UDPPeerLink:
    def __init__(self, robot_id: str, my_index: int, peer_indices: List[int],
                 on_message: Callable[[dict], None], host: str = "127.0.0.1"):
        self.robot_id = robot_id
        self.host = host
        self.my_port = BASE_PORT + my_index
        self.peer_ports = [BASE_PORT + i for i in peer_indices if i != my_index]
        self.on_message = on_message
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, self.my_port))
        self._sock.settimeout(0.2)
        self._running = False
        self._rx_thread = None
        # extra "observer" ports (e.g. the dashboard) that silently listen in
        self.observer_ports: List[int] = []

    def start(self):
        self._running = True
        self._rx_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._rx_thread.start()

    def stop(self):
        self._running = False
        if self._rx_thread:
            self._rx_thread.join(timeout=1)
        self._sock.close()

    def _recv_loop(self):
        while self._running:
            try:
                data, _addr = self._sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if msg.get("robot_id") == self.robot_id:
                continue  # ignore our own broadcast
            self.on_message(msg)

    def broadcast(self, msg: dict):
        """Send directly to every peer's UDP port -- this IS the 'mesh'.
        No intermediary process ever sees or routes this except the OS
        network stack, exactly as it would be over real radios."""
        payload = json.dumps(msg).encode("utf-8")
        for port in self.peer_ports + self.observer_ports:
            try:
                self._sock.sendto(payload, (self.host, port))
            except OSError:
                pass
