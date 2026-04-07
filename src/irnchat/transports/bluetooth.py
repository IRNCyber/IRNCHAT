from __future__ import annotations

import asyncio
import socket
import sys
from dataclasses import dataclass

from .link import TextLink


class BluetoothNotSupported(RuntimeError):
    pass


def explain_limitation() -> str:
    return (
        "Bluetooth transport requires Linux + BlueZ (RFCOMM). "
        "In Docker this usually needs host networking and device access; "
        "on Windows/macOS Docker Desktop it is typically not available."
    )


def _ensure_linux() -> None:
    if not sys.platform.startswith("linux"):
        raise BluetoothNotSupported(explain_limitation())
    if not hasattr(socket, "AF_BLUETOOTH") or not hasattr(socket, "BTPROTO_RFCOMM"):
        raise BluetoothNotSupported("Python Bluetooth RFCOMM sockets not available on this system.")


async def _read_exact(loop: asyncio.AbstractEventLoop, sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = await loop.sock_recv(sock, n - len(buf))
        if not chunk:
            raise EOFError
        buf.extend(chunk)
    return bytes(buf)


@dataclass
class RfcommTextLink(TextLink):
    _sock: socket.socket
    _loop: asyncio.AbstractEventLoop

    async def send(self, data: str) -> None:
        raw = data.encode("utf-8")
        header = len(raw).to_bytes(4, "big")
        await self._loop.sock_sendall(self._sock, header + raw)

    async def recv(self) -> str:
        header = await _read_exact(self._loop, self._sock, 4)
        ln = int.from_bytes(header, "big")
        if ln <= 0 or ln > 2**20:
            raise RuntimeError("invalid frame length")
        raw = await _read_exact(self._loop, self._sock, ln)
        return raw.decode("utf-8", errors="strict")

    async def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass

    def __aiter__(self):
        async def gen():
            while True:
                try:
                    yield await self.recv()
                except (EOFError, OSError):
                    return

        return gen()


async def rfcomm_host(*, bind_addr: str = "00:00:00:00:00:00", channel: int = 1) -> TextLink:
    """
    Listen for a single inbound RFCOMM connection and return a framed TextLink.

    Requires the host Bluetooth adapter to be up and discoverable/pairable as
    needed by your environment.
    """

    _ensure_linux()
    loop = asyncio.get_running_loop()

    srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    srv.setblocking(False)
    try:
        srv.bind((bind_addr, channel))
        srv.listen(1)
        client, _addr = await loop.sock_accept(srv)
        client.setblocking(False)
        return RfcommTextLink(_sock=client, _loop=loop)
    finally:
        try:
            srv.close()
        except Exception:
            pass


async def rfcomm_join(*, addr: str, channel: int = 1) -> TextLink:
    _ensure_linux()
    loop = asyncio.get_running_loop()

    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.setblocking(False)
    try:
        await loop.sock_connect(sock, (addr, channel))
        return RfcommTextLink(_sock=sock, _loop=loop)
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise

