from __future__ import annotations

import argparse
import asyncio
import contextlib
import os

from rich.console import Console
from rich.panel import Panel

from .core import IRNChatCore
from .io import ainput
from .transports import bluetooth as bt
from .ui_server import run_ui


console = Console()


async def _events_loop(core: IRNChatCore) -> None:
    q = core.events_queue()
    while True:
        ev = await q.get()
        if ev.type == "message":
            if ev.who == "me":
                console.print(f"[green]you>[/green] {ev.text}")
            else:
                console.print(f"[cyan]peer>[/cyan] {ev.text}")
        elif ev.type == "connected":
            console.print(
                Panel.fit(
                    f"Medium: {ev.medium}\nSession: {ev.session_id}\nType messages and press Enter. Use /quit to exit.",
                    title="irnchat",
                )
            )
        elif ev.type == "status":
            console.print(f"[dim]{ev.text}[/dim]")
        elif ev.type == "error":
            console.print(f"[red]{ev.text}[/red]")
        elif ev.type == "disconnected":
            console.print(f"[yellow]{ev.text}[/yellow]")


async def _send_loop(core: IRNChatCore) -> None:
    while True:
        line = await ainput("")
        if not line:
            continue
        if line.strip().lower() in {"/quit", "/exit"}:
            await core.disconnect()
            return
        await core.send(line)


async def _run_chat(core: IRNChatCore, connect_coro) -> None:
    ev_task = asyncio.create_task(_events_loop(core))
    try:
        await connect_coro
        snd_task = asyncio.create_task(_send_loop(core))
        await snd_task
    finally:
        ev_task.cancel()
        with contextlib.suppress(Exception):
            await core.disconnect()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="irnchat", description="IRNCHAT: local-range E2EE chat over Wi-Fi/Bluetooth.")
    sub = p.add_subparsers(dest="cmd", required=True)

    hp = sub.add_parser("wifi-host", help="Host a room on Wi-Fi/LAN (WebSocket + UDP discovery).")
    hp.add_argument("--bind", default="0.0.0.0")
    hp.add_argument("--port", type=int, default=8765)
    hp.add_argument("--pass", dest="passphrase", default=None)

    jp = sub.add_parser("wifi-join", help="Join a room on Wi-Fi/LAN.")
    jp.add_argument("--url", default=None)
    jp.add_argument("--pass", dest="passphrase", default=None)

    bp = sub.add_parser("bluetooth", help="Bluetooth RFCOMM transport (Linux/BlueZ).")
    bp.add_argument("mode", choices=["host", "join"])
    bp.add_argument("--addr", default=None, help="Peer Bluetooth address (required for join).")
    bp.add_argument("--bind-addr", default="00:00:00:00:00:00")
    bp.add_argument("--channel", type=int, default=1)
    bp.add_argument("--pass", dest="passphrase", default=None)

    ap = sub.add_parser("auto-host", help="Host on Wi-Fi + Bluetooth; use whichever connects first.")
    ap.add_argument("--wifi-bind", default="0.0.0.0")
    ap.add_argument("--wifi-port", type=int, default=8765)
    ap.add_argument("--bt-bind-addr", default="00:00:00:00:00:00")
    ap.add_argument("--bt-channel", type=int, default=1)
    ap.add_argument("--pass", dest="passphrase", default=None)

    aj = sub.add_parser("auto-join", help="Join via Bluetooth if provided, else Wi-Fi.")
    aj.add_argument("--url", default=None)
    aj.add_argument("--bt-addr", default=None)
    aj.add_argument("--bt-channel", type=int, default=1)
    aj.add_argument("--pass", dest="passphrase", default=None)

    up = sub.add_parser("ui", help="Run the local web UI (FastAPI).")
    up.add_argument("--host", default="127.0.0.1")
    up.add_argument("--port", type=int, default=8000)

    gp = sub.add_parser("gui", help="Run a minimal desktop GUI (Tkinter).")
    gp.add_argument("--pass", dest="passphrase", default=None)

    sp = sub.add_parser("selftest", help="Run a quick local Wi-Fi chat self-test (host+join on localhost).")
    sp.add_argument("--pass", dest="passphrase", default="testpass")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "ui":
        console.print(f"[green]UI:[/green] open http://{args.host}:{args.port}")
        run_ui(host=args.host, port=args.port)
        return 0

    if args.cmd == "gui":
        passphrase = getattr(args, "passphrase", None) or os.environ.get("IRNCHAT_PASSPHRASE", "")
        if not passphrase:
            console.print("[red]Passphrase is required.[/red]")
            console.print("[dim]Use --pass or set IRNCHAT_PASSPHRASE.[/dim]")
            return 2
        # Lazy import so Docker images without Tk do not fail to start.
        from .gui_tk import run_tk_gui

        run_tk_gui(passphrase=passphrase)
        return 0

    if args.cmd == "selftest":
        async def go():
            host = IRNChatCore(passphrase=args.passphrase)
            join = IRNChatCore(passphrase=args.passphrase)
            await host.wifi_host(bind="127.0.0.1", port=9876)

            async def wait_connected(core: IRNChatCore, name: str) -> None:
                q = core.events_queue()
                while True:
                    ev = await q.get()
                    if ev.type == "connected":
                        return

            await asyncio.wait_for(join.wifi_join(url="ws://127.0.0.1:9876/ws"), timeout=5)
            await asyncio.wait_for(wait_connected(host, "host"), timeout=5)
            await asyncio.wait_for(wait_connected(join, "join"), timeout=5)

            await join.send("hello")
            await asyncio.sleep(0.2)
            await host.send("world")
            await asyncio.sleep(0.2)
            await host.disconnect()
            await join.disconnect()

        asyncio.run(go())
        console.print("[green]Self-test complete.[/green]")
        return 0

    passphrase = getattr(args, "passphrase", None) or os.environ.get("IRNCHAT_PASSPHRASE", "")
    if not passphrase:
        console.print("[red]Passphrase is required.[/red]")
        console.print("[dim]Use --pass or set IRNCHAT_PASSPHRASE.[/dim]")
        return 2

    try:
        core = IRNChatCore(passphrase=passphrase)

        if args.cmd == "wifi-host":
            asyncio.run(_run_chat(core, core.wifi_host(bind=args.bind, port=args.port)))
        elif args.cmd == "wifi-join":
            asyncio.run(_run_chat(core, core.wifi_join(url=args.url)))
        elif args.cmd == "bluetooth":
            if args.mode == "host":
                asyncio.run(_run_chat(core, core.bt_host(bind_addr=args.bind_addr, channel=args.channel)))
            else:
                if not args.addr:
                    raise RuntimeError("--addr is required for bluetooth join")
                asyncio.run(_run_chat(core, core.bt_join(addr=args.addr, channel=args.channel)))
        elif args.cmd == "auto-host":
            asyncio.run(
                _run_chat(
                    core,
                    core.auto_host(
                        wifi_bind=args.wifi_bind,
                        wifi_port=args.wifi_port,
                        bt_bind_addr=args.bt_bind_addr,
                        bt_channel=args.bt_channel,
                    ),
                )
            )
        elif args.cmd == "auto-join":
            asyncio.run(_run_chat(core, core.auto_join(wifi_url=args.url, bt_addr=args.bt_addr, bt_channel=args.bt_channel)))
        else:
            raise RuntimeError("unknown command")
        return 0
    except bt.BluetoothNotSupported as e:
        console.print(f"[yellow]{e}[/yellow]")
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
