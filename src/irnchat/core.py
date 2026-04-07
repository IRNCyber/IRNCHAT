from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

import websockets

from .identity import Identity, load_or_create_identity
from .session import E2EESession, handshake_initiator, handshake_responder
from .transports import bluetooth as bt
from .transports.link import WebSocketLink
from .transports.wifi import discovery_broadcast_task, discovery_listen, new_room_and_port


Medium = Literal["Wi-Fi/LAN", "Bluetooth(RFCOMM)"]


@dataclass(frozen=True)
class CoreEvent:
    type: Literal["status", "connected", "disconnected", "message", "error"]
    text: str
    who: Literal["me", "peer", "system"] = "system"
    medium: str | None = None
    session_id: str | None = None


class IRNChatCore:
    """
    Unified app core used by CLI, Web UI, and desktop GUI.
    """

    def __init__(self, *, passphrase: str, identity: Identity | None = None) -> None:
        if not passphrase:
            raise ValueError("passphrase required")
        self.identity = identity or load_or_create_identity()
        self.passphrase = passphrase

        self._lock = asyncio.Lock()
        self._events: asyncio.Queue[CoreEvent] = asyncio.Queue()

        self._peer: E2EESession | None = None
        self._medium: str | None = None
        self._recv_task: asyncio.Task | None = None

        self._wifi_server = None
        self._wifi_broadcast_task: asyncio.Task | None = None

    def events_queue(self) -> asyncio.Queue[CoreEvent]:
        return self._events

    async def emit(self, ev: CoreEvent) -> None:
        await self._events.put(ev)

    async def disconnect(self) -> None:
        async with self._lock:
            if self._recv_task:
                self._recv_task.cancel()
                self._recv_task = None
            if self._peer:
                try:
                    await self._peer.ws.close()
                except Exception:
                    pass
                self._peer = None
            self._medium = None

            if self._wifi_server is not None:
                try:
                    self._wifi_server.close()
                    await self._wifi_server.wait_closed()
                except Exception:
                    pass
                self._wifi_server = None
            if self._wifi_broadcast_task:
                self._wifi_broadcast_task.cancel()
                self._wifi_broadcast_task = None

        await self.emit(CoreEvent(type="disconnected", text="Disconnected."))

    async def _set_connected(self, *, medium: str, session: E2EESession) -> None:
        async with self._lock:
            if self._peer is not None:
                # Only one peer supported per core instance.
                try:
                    await session.ws.close()
                except Exception:
                    pass
                await self.emit(CoreEvent(type="error", text="A peer is already connected."))
                return
            self._peer = session
            self._medium = medium
            self._recv_task = asyncio.create_task(self._recv_loop(session))
        await self.emit(
            CoreEvent(type="connected", text=f"Connected via {medium}.", medium=medium, session_id=session.session_id)
        )

    async def _recv_loop(self, session: E2EESession) -> None:
        try:
            async for raw in session.ws:
                text = session.unpack_message(raw)
                if text is None:
                    await self.emit(CoreEvent(type="error", text="Failed to decrypt (wrong passphrase or replay)."))
                    continue
                await self.emit(CoreEvent(type="message", who="peer", text=text))
        except Exception:
            pass
        finally:
            await self.disconnect()

    async def send(self, text: str) -> None:
        async with self._lock:
            peer = self._peer
        if not peer:
            raise RuntimeError("not connected")
        await peer.ws.send(peer.pack_message(text))
        await self.emit(CoreEvent(type="message", who="me", text=text))

    async def wifi_host(self, *, bind: str = "0.0.0.0", port: int = 8765) -> None:
        await self.disconnect()
        room, ws_port = new_room_and_port(port)
        await self.emit(CoreEvent(type="status", text=f"Hosting room {room} (Wi-Fi/LAN). Waiting for peer..."))

        async def handler(ws):
            async with self._lock:
                if self._peer is not None:
                    await ws.close()
                    return
            link = WebSocketLink(ws)
            session = await handshake_responder(link, self.passphrase)
            await self._set_connected(medium="Wi-Fi/LAN", session=session)
            await ws.wait_closed()

        self._wifi_broadcast_task = asyncio.create_task(discovery_broadcast_task(room=room, ws_port=ws_port))
        self._wifi_server = await websockets.serve(handler, bind, ws_port, max_size=2**20)

    async def wifi_join(self, *, url: str | None = None) -> None:
        await self.disconnect()
        if not url:
            await self.emit(CoreEvent(type="status", text="Searching LAN for rooms (UDP broadcast)..."))
            hits = await discovery_listen(timeout_s=8.0)
            if not hits:
                raise RuntimeError("no rooms discovered")
            url = hits[0].ws_url
        await self.emit(CoreEvent(type="status", text="Connecting via Wi-Fi..."))
        try:
            ws = await websockets.connect(url, max_size=2**20, open_timeout=6)
        except Exception as e:
            raise RuntimeError(
                "Wi-Fi connect failed. Use a URL like ws://<host-ip>:8765/ws (not 0.0.0.0). "
                "If hosting+joining on the same machine/container, use ws://127.0.0.1:8765/ws."
            ) from e
        link = WebSocketLink(ws)
        session = await handshake_initiator(link, self.passphrase)
        await self._set_connected(medium="Wi-Fi/LAN", session=session)

    async def bt_host(self, *, bind_addr: str = "00:00:00:00:00:00", channel: int = 1) -> None:
        await self.disconnect()
        await self.emit(CoreEvent(type="status", text="Hosting (Bluetooth RFCOMM). Waiting for peer..."))
        link = await bt.rfcomm_host(bind_addr=bind_addr, channel=channel)
        session = await handshake_responder(link, self.passphrase)
        await self._set_connected(medium="Bluetooth(RFCOMM)", session=session)

    async def bt_join(self, *, addr: str, channel: int = 1) -> None:
        await self.disconnect()
        await self.emit(CoreEvent(type="status", text="Connecting via Bluetooth..."))
        link = await bt.rfcomm_join(addr=addr, channel=channel)
        session = await handshake_initiator(link, self.passphrase)
        await self._set_connected(medium="Bluetooth(RFCOMM)", session=session)

    async def auto_host(
        self,
        *,
        wifi_bind: str = "0.0.0.0",
        wifi_port: int = 8765,
        bt_bind_addr: str = "00:00:00:00:00:00",
        bt_channel: int = 1,
    ) -> None:
        await self.disconnect()
        room, ws_port = new_room_and_port(wifi_port)
        await self.emit(CoreEvent(type="status", text=f"Auto-hosting room {room} (Wi-Fi + Bluetooth). Waiting..."))

        connected: asyncio.Future[tuple[str, E2EESession]] = asyncio.get_running_loop().create_future()
        done = asyncio.Event()

        async def wifi_handler(ws):
            async with self._lock:
                if self._peer is not None:
                    await ws.close()
                    return
            link = WebSocketLink(ws)
            session = await handshake_responder(link, self.passphrase)
            if not connected.done():
                connected.set_result(("Wi-Fi/LAN", session))
            await ws.wait_closed()

        async def wifi_task():
            self._wifi_broadcast_task = asyncio.create_task(discovery_broadcast_task(room=room, ws_port=ws_port))
            server = await websockets.serve(wifi_handler, wifi_bind, ws_port, max_size=2**20)
            try:
                await connected
            finally:
                self._wifi_broadcast_task.cancel()
                server.close()
                await server.wait_closed()

        async def bt_task():
            try:
                link = await bt.rfcomm_host(bind_addr=bt_bind_addr, channel=bt_channel)
            except Exception:
                return
            session = await handshake_responder(link, self.passphrase)
            if not connected.done():
                connected.set_result(("Bluetooth(RFCOMM)", session))
            else:
                await link.close()

        wifi_t = asyncio.create_task(wifi_task())
        bt_t = asyncio.create_task(bt_task())
        try:
            medium, session = await connected
            await self._set_connected(medium=medium, session=session)
        finally:
            done.set()
            bt_t.cancel()
            wifi_t.cancel()

    async def auto_join(
        self,
        *,
        wifi_url: str | None = None,
        bt_addr: str | None = None,
        bt_channel: int = 1,
        bt_timeout_s: float = 6.0,
    ) -> None:
        if bt_addr:
            try:
                await asyncio.wait_for(self.bt_join(addr=bt_addr, channel=bt_channel), bt_timeout_s)
                return
            except Exception:
                await self.emit(CoreEvent(type="status", text="Bluetooth failed; falling back to Wi-Fi..."))
        await self.wifi_join(url=wifi_url)
