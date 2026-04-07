from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from dataclasses import dataclass


DISCOVERY_PORT = 9999
DEFAULT_CHAT_PORT = 8765


@dataclass(frozen=True)
class DiscoveryHit:
    room: str
    ws_url: str
    seen_at: float


def _make_room_id() -> str:
    return os.urandom(6).hex()


def make_discovery_packet(*, room: str, ws_port: int) -> bytes:
    # Keep this intentionally minimal: no usernames/device names.
    payload = {"v": 1, "room": room, "ws_port": ws_port, "t": "irnchat"}
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


async def discovery_broadcast_task(*, room: str, ws_port: int, interval_s: float = 2.0) -> None:
    packet = make_discovery_packet(room=room, ws_port=ws_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        while True:
            try:
                sock.sendto(packet, ("255.255.255.255", DISCOVERY_PORT))
            except OSError:
                pass
            await asyncio.sleep(interval_s)
    finally:
        sock.close()


async def discovery_listen(*, timeout_s: float = 10.0) -> list[DiscoveryHit]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", DISCOVERY_PORT))
    sock.setblocking(False)

    hits: dict[tuple[str, str], DiscoveryHit] = {}
    deadline = time.time() + timeout_s
    try:
        while time.time() < deadline:
            try:
                data, addr = await asyncio.wait_for(asyncio.get_running_loop().sock_recvfrom(sock, 2048), 0.5)
            except asyncio.TimeoutError:
                continue
            except OSError:
                continue
            ip, _port = addr
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if not isinstance(msg, dict) or msg.get("t") != "irnchat" or msg.get("v") != 1:
                continue
            room = str(msg.get("room") or "")
            ws_port = int(msg.get("ws_port") or 0)
            if not room or not (1 <= ws_port <= 65535):
                continue
            # Connect back to the broadcaster's source IP on the advertised port.
            ws_url = f"ws://{ip}:{ws_port}/ws"
            key = (room, ws_url)
            hits[key] = DiscoveryHit(room=room, ws_url=ws_url, seen_at=time.time())
        return sorted(hits.values(), key=lambda h: h.seen_at, reverse=True)
    finally:
        sock.close()


def new_room_and_port(requested_port: int | None) -> tuple[str, int]:
    return _make_room_id(), (requested_port or DEFAULT_CHAT_PORT)
