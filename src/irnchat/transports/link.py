from __future__ import annotations

from typing import AsyncIterator, Protocol


class TextLink(Protocol):
    async def send(self, data: str) -> None: ...

    async def recv(self) -> str: ...

    async def close(self) -> None: ...

    def __aiter__(self) -> AsyncIterator[str]: ...


class WebSocketLink:
    def __init__(self, ws):
        self._ws = ws

    async def send(self, data: str) -> None:
        await self._ws.send(data)

    async def recv(self) -> str:
        return await self._ws.recv()

    async def close(self) -> None:
        await self._ws.close()

    def __aiter__(self):
        return self._ws.__aiter__()

