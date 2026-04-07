from __future__ import annotations

import asyncio
import sys


async def ainput(prompt: str = "") -> str:
    if prompt:
        print(prompt, end="", flush=True)
    loop = asyncio.get_running_loop()
    line = await loop.run_in_executor(None, sys.stdin.readline)
    return line.rstrip("\r\n")

