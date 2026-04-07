from __future__ import annotations

import asyncio
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from .core import CoreEvent, IRNChatCore


@dataclass
class _State:
    loop: asyncio.AbstractEventLoop | None = None
    thread: threading.Thread | None = None
    core: IRNChatCore | None = None
    events_task: asyncio.Task | None = None


class TkIRNChatApp:
    def __init__(self, *, passphrase: str) -> None:
        self._state = _State()
        self._uiq: queue.Queue[CoreEvent] = queue.Queue()

        self.root = tk.Tk()
        self.root.title("IRNCHAT")
        self.root.geometry("920x640")

        self.passphrase = tk.StringVar(value=passphrase)
        self.mode = tk.StringVar(value="host")
        self.medium = tk.StringVar(value="auto")
        self.bind = tk.StringVar(value="0.0.0.0")
        self.port = tk.StringVar(value="8765")
        self.url = tk.StringVar(value="")
        self.btaddr = tk.StringVar(value="")
        self.btchan = tk.StringVar(value="1")
        self.status = tk.StringVar(value="disconnected")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_events)

        self._ensure_loop()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="Mode").grid(row=0, column=0, sticky="w")
        ttk.Combobox(top, textvariable=self.mode, values=["host", "join"], width=8, state="readonly").grid(
            row=0, column=1, padx=(6, 16), sticky="w"
        )

        ttk.Label(top, text="Medium").grid(row=0, column=2, sticky="w")
        ttk.Combobox(top, textvariable=self.medium, values=["auto", "wifi", "bt"], width=10, state="readonly").grid(
            row=0, column=3, padx=(6, 16), sticky="w"
        )

        ttk.Label(top, text="Passphrase").grid(row=0, column=4, sticky="w")
        ttk.Entry(top, textvariable=self.passphrase, width=22, show="•").grid(row=0, column=5, padx=(6, 16), sticky="w")

        ttk.Label(top, textvariable=self.status, foreground="#555").grid(row=0, column=6, sticky="e")
        top.columnconfigure(6, weight=1)

        conn = ttk.LabelFrame(self.root, text="Connection", padding=12)
        conn.pack(fill="x", padx=12, pady=(0, 10))

        ttk.Label(conn, text="Bind").grid(row=0, column=0, sticky="w")
        ttk.Entry(conn, textvariable=self.bind, width=18).grid(row=0, column=1, padx=(6, 16), sticky="w")

        ttk.Label(conn, text="Port").grid(row=0, column=2, sticky="w")
        ttk.Entry(conn, textvariable=self.port, width=10).grid(row=0, column=3, padx=(6, 16), sticky="w")

        ttk.Label(conn, text="Wi-Fi URL (join)").grid(row=0, column=4, sticky="w")
        ttk.Entry(conn, textvariable=self.url, width=34).grid(row=0, column=5, padx=(6, 16), sticky="w")

        ttk.Label(conn, text="BT addr (join)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(conn, textvariable=self.btaddr, width=18).grid(row=1, column=1, padx=(6, 16), sticky="w", pady=(8, 0))

        ttk.Label(conn, text="BT channel").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(conn, textvariable=self.btchan, width=10).grid(row=1, column=3, padx=(6, 16), sticky="w", pady=(8, 0))

        btns = ttk.Frame(conn)
        btns.grid(row=1, column=5, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="Connect", command=self._connect).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Disconnect", command=self._disconnect).pack(side="left")

        chat = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        chat.pack(fill="both", expand=True)

        self.text = tk.Text(chat, wrap="word", height=20)
        self.text.pack(fill="both", expand=True)
        self.text.configure(state="disabled")

        send = ttk.Frame(chat)
        send.pack(fill="x", pady=(10, 0))
        self.entry = ttk.Entry(send)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _e: self._send())
        ttk.Button(send, text="Send", command=self._send).pack(side="left", padx=(8, 0))

    def _append(self, line: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    def _ensure_loop(self) -> None:
        if self._state.loop:
            return

        loop = asyncio.new_event_loop()

        def runner():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=runner, name="irnchat-async", daemon=True)
        t.start()
        self._state.loop = loop
        self._state.thread = t

    def _run_coro(self, coro):
        if not self._state.loop:
            raise RuntimeError("loop not ready")
        return asyncio.run_coroutine_threadsafe(coro, self._state.loop)

    async def _start_core(self) -> IRNChatCore:
        if not self.passphrase.get():
            raise RuntimeError("passphrase required")
        core = IRNChatCore(passphrase=self.passphrase.get())
        self._state.core = core

        async def pump():
            q = core.events_queue()
            while True:
                ev = await q.get()
                self._uiq.put(ev)

        self._state.events_task = asyncio.create_task(pump())
        return core

    def _connect(self) -> None:
        try:
            self.status.set("connecting...")
            self._run_coro(self._connect_async())
        except Exception as e:
            self.status.set(f"error: {e}")

    async def _connect_async(self) -> None:
        await self._disconnect_async()
        core = await self._start_core()

        mode = self.mode.get()
        medium = self.medium.get()
        bind = self.bind.get() or "0.0.0.0"
        port = int(self.port.get() or "8765")
        url = self.url.get().strip() or None
        btaddr = self.btaddr.get().strip() or None
        btchan = int(self.btchan.get() or "1")

        if mode == "host":
            if medium == "wifi":
                await core.wifi_host(bind=bind, port=port)
            elif medium == "bt":
                await core.bt_host(channel=btchan)
            else:
                await core.auto_host(wifi_bind=bind, wifi_port=port, bt_channel=btchan)
        else:
            if medium == "wifi":
                await core.wifi_join(url=url)
            elif medium == "bt":
                if not btaddr:
                    raise RuntimeError("BT addr required")
                await core.bt_join(addr=btaddr, channel=btchan)
            else:
                await core.auto_join(wifi_url=url, bt_addr=btaddr, bt_channel=btchan)

    def _disconnect(self) -> None:
        self._run_coro(self._disconnect_async())

    async def _disconnect_async(self) -> None:
        if self._state.core:
            await self._state.core.disconnect()
        if self._state.events_task:
            self._state.events_task.cancel()
            self._state.events_task = None
        self._state.core = None

    def _send(self) -> None:
        msg = self.entry.get().strip()
        if not msg:
            return
        self.entry.delete(0, "end")
        self._run_coro(self._send_async(msg))

    async def _send_async(self, msg: str) -> None:
        if not self._state.core:
            raise RuntimeError("not connected")
        await self._state.core.send(msg)

    def _drain_events(self) -> None:
        try:
            while True:
                ev = self._uiq.get_nowait()
                if ev.type == "message":
                    prefix = "you> " if ev.who == "me" else "peer> "
                    self._append(prefix + ev.text)
                elif ev.type == "connected":
                    self.status.set(f"connected ({ev.medium})")
                    self._append(f"system> connected ({ev.medium}) session={ev.session_id}")
                elif ev.type == "status":
                    self.status.set(ev.text)
                    self._append("system> " + ev.text)
                elif ev.type == "error":
                    self.status.set("error")
                    self._append("error> " + ev.text)
                elif ev.type == "disconnected":
                    self.status.set("disconnected")
                    self._append("system> disconnected")
        except queue.Empty:
            pass
        self.root.after(120, self._drain_events)

    def _on_close(self) -> None:
        try:
            self._run_coro(self._disconnect_async()).result(timeout=2)
        except Exception:
            pass
        if self._state.loop:
            self._state.loop.call_soon_threadsafe(self._state.loop.stop)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def run_tk_gui(*, passphrase: str) -> None:
    app = TkIRNChatApp(passphrase=passphrase)
    app.run()
