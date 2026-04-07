from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .core import IRNChatCore


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>IRNCHAT</title>
  <style>
    :root{--bg:#0b1220;--card:#101a2f;--muted:#93a4c7;--text:#e7eeff;--accent:#5eead4;--danger:#fb7185}
    *{box-sizing:border-box} body{margin:0;font:14px/1.4 system-ui,Segoe UI,Roboto,Arial;background:linear-gradient(180deg,#070b14,#0b1220);color:var(--text)}
    .wrap{max-width:1000px;margin:0 auto;padding:20px}
    .top{display:flex;gap:12px;flex-wrap:wrap;align-items:center;justify-content:space-between}
    .brand{font-weight:800;letter-spacing:.5px}
    .pill{padding:6px 10px;border:1px solid rgba(255,255,255,.12);border-radius:999px;color:var(--muted)}
    .grid{display:grid;grid-template-columns:360px 1fr;gap:14px;margin-top:14px}
    .card{background:rgba(16,26,47,.92);border:1px solid rgba(255,255,255,.10);border-radius:14px;box-shadow:0 10px 30px rgba(0,0,0,.25)}
    .card h3{margin:0;padding:14px 14px 8px 14px;font-size:13px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.12em}
    .pad{padding:14px}
    label{display:block;color:var(--muted);font-size:12px;margin:10px 0 6px}
    input,select,button{width:100%;padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.14);background:#0c1428;color:var(--text);outline:none}
    input:focus,select:focus{border-color:rgba(94,234,212,.55);box-shadow:0 0 0 3px rgba(94,234,212,.12)}
    .row{display:flex;gap:10px}
    .row > *{flex:1}
    button{cursor:pointer;background:linear-gradient(180deg,rgba(94,234,212,.22),rgba(94,234,212,.06));border-color:rgba(94,234,212,.4)}
    button.secondary{background:transparent;border-color:rgba(255,255,255,.14)}
    button.danger{background:linear-gradient(180deg,rgba(251,113,133,.25),rgba(251,113,133,.08));border-color:rgba(251,113,133,.45)}
    .status{font-size:12px;color:var(--muted)}
    .chat{display:flex;flex-direction:column;height:680px}
    .msgs{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
    .msg{max-width:80%;padding:10px 12px;border-radius:12px;border:1px solid rgba(255,255,255,.10);background:rgba(255,255,255,.04)}
    .me{align-self:flex-end;border-color:rgba(94,234,212,.25);background:rgba(94,234,212,.08)}
    .peer{align-self:flex-start}
    .meta{font-size:11px;color:var(--muted);margin-bottom:4px}
    .send{border-top:1px solid rgba(255,255,255,.10);padding:12px;display:flex;gap:10px}
    .send input{flex:1}
    .send button{width:140px}
    .hint{font-size:12px;color:var(--muted);margin-top:10px}
    code{color:var(--accent)}
    @media (max-width: 900px){.grid{grid-template-columns:1fr}.chat{height:70vh}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div class="brand">IRNCHAT</div>
      <div class="pill" id="pill">disconnected</div>
    </div>

    <div class="grid">
      <div class="card">
        <h3>Connection</h3>
        <div class="pad">
          <label>Mode</label>
          <select id="mode">
            <option value="host">Host</option>
            <option value="join">Join</option>
          </select>

          <label>Medium</label>
          <select id="medium">
            <option value="auto">Auto (Wi‑Fi + Bluetooth)</option>
            <option value="wifi">Wi‑Fi/LAN</option>
            <option value="bt">Bluetooth (RFCOMM)</option>
          </select>

          <div class="row">
            <div>
              <label>Bind (host)</label>
              <input id="bind" value="0.0.0.0" />
            </div>
            <div>
              <label>Port (host)</label>
              <input id="port" value="8765" />
            </div>
          </div>

          <label>URL (join; optional)</label>
          <input id="url" placeholder="ws://192.168.1.10:8765/ws" />

          <div class="row">
            <div>
              <label>BT addr (join; optional)</label>
              <input id="btaddr" placeholder="AA:BB:CC:DD:EE:FF" />
            </div>
            <div>
              <label>BT channel</label>
              <input id="btchan" value="1" />
            </div>
          </div>

          <label>Passphrase</label>
          <input id="pass" type="password" placeholder="required for privacy" />

          <div class="row" style="margin-top:12px">
            <button id="connect">Connect</button>
            <button class="danger" id="disconnect">Disconnect</button>
          </div>

          <div class="hint">
            Local-only: Wi‑Fi discovery uses UDP broadcast on <code>9999/udp</code>.
            Bluetooth requires Linux + BlueZ. If Wi‑Fi discovery is blocked, paste a URL.
          </div>
        </div>
      </div>

      <div class="card chat">
        <h3>Chat</h3>
        <div class="msgs" id="msgs"></div>
        <div class="send">
          <input id="text" placeholder="Type a message…" />
          <button class="secondary" id="send">Send</button>
        </div>
      </div>
    </div>

    <div class="status" id="status" style="margin-top:12px"></div>
  </div>

<script>
  const pill = document.getElementById('pill');
  const status = document.getElementById('status');
  const msgs = document.getElementById('msgs');
  const text = document.getElementById('text');

  let ws;
  function setPill(s){pill.textContent=s;}
  function logStatus(s){status.textContent=s;}
  function addMsg(who, body){
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + (who === 'me' ? 'me' : 'peer');
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = who === 'me' ? 'you' : 'peer';
    const b = document.createElement('div');
    b.textContent = body;
    wrap.appendChild(meta); wrap.appendChild(b);
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function ensureWs(){
    if (ws && ws.readyState === WebSocket.OPEN) return ws;
    ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ui');
    ws.onopen = () => { setPill('connected'); logStatus('UI connected.'); };
    ws.onclose = () => { setPill('disconnected'); logStatus('UI disconnected.'); };
    ws.onerror = () => { logStatus('UI socket error.'); };
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.evt === 'status') logStatus(m.text);
      if (m.evt === 'message') addMsg(m.from, m.text);
      if (m.evt === 'info') logStatus(m.text);
      if (m.evt === 'error') logStatus('Error: ' + m.text);
    };
    return ws;
  }

  document.getElementById('connect').onclick = () => {
    const mode = document.getElementById('mode').value;
    const medium = document.getElementById('medium').value;
    const bind = document.getElementById('bind').value;
    const port = parseInt(document.getElementById('port').value, 10);
    const url = document.getElementById('url').value || null;
    const btaddr = document.getElementById('btaddr').value || null;
    const btchan = parseInt(document.getElementById('btchan').value || '1', 10);
    const pass = document.getElementById('pass').value || '';
    ensureWs().send(JSON.stringify({cmd:'connect', mode, medium, bind, port, url, btaddr, btchan, pass}));
  };
  document.getElementById('disconnect').onclick = () => ensureWs().send(JSON.stringify({cmd:'disconnect'}));
  document.getElementById('send').onclick = () => {
    const t = text.value.trim();
    if (!t) return;
    ensureWs().send(JSON.stringify({cmd:'send', text:t}));
    text.value = '';
  };
  text.addEventListener('keydown', (e) => { if (e.key === 'Enter') document.getElementById('send').click(); });
  ensureWs();
</script>
</body>
</html>"""


@dataclass
class UISession:
    ws: WebSocket
    lock: asyncio.Lock
    core: IRNChatCore | None = None
    events_task: asyncio.Task | None = None
    ws_closed: bool = False

    async def _send(self, payload: dict) -> None:
        if self.ws_closed:
            return
        try:
            await self.ws.send_text(_json_dumps(payload))
        except Exception:
            # The socket is already closing/closed; never raise from cleanup paths.
            self.ws_closed = True

    async def disconnect(self, *, notify: bool = True) -> None:
        async with self.lock:
            if self.events_task:
                self.events_task.cancel()
                self.events_task = None
            if self.core:
                try:
                    await self.core.disconnect()
                except Exception:
                    pass
                self.core = None
        if notify:
            await self._send({"evt": "status", "text": "Disconnected."})

    async def cleanup(self) -> None:
        # Same as disconnect but never tries to write to the websocket.
        async with self.lock:
            self.ws_closed = True
            if self.events_task:
                self.events_task.cancel()
                self.events_task = None
            if self.core:
                try:
                    await self.core.disconnect()
                except Exception:
                    pass
                self.core = None

    async def _events_loop(self, core: IRNChatCore) -> None:
        q = core.events_queue()
        while True:
            ev = await q.get()
            if ev.type == "message":
                await self._send({"evt": "message", "from": ev.who, "text": ev.text})
            elif ev.type == "connected":
                await self._send({"evt": "status", "text": f"Connected via {ev.medium}. Session {ev.session_id}."})
            elif ev.type == "status":
                await self._send({"evt": "status", "text": ev.text})
            elif ev.type == "error":
                await self._send({"evt": "error", "text": ev.text})
            elif ev.type == "disconnected":
                await self._send({"evt": "status", "text": ev.text})

    async def connect(
        self,
        *,
        mode: str,
        medium: str,
        bind: str,
        port: int,
        url: str | None,
        btaddr: str | None,
        btchan: int,
        passphrase: str,
    ) -> None:
        await self.disconnect(notify=False)
        core = IRNChatCore(passphrase=passphrase)
        async with self.lock:
            self.core = core
            self.events_task = asyncio.create_task(self._events_loop(core))

        if mode == "host":
            if medium == "wifi":
                await core.wifi_host(bind=bind, port=port)
            elif medium == "bt":
                await core.bt_host(channel=btchan)
            else:
                await core.auto_host(wifi_bind=bind, wifi_port=port, bt_channel=btchan)
        elif mode == "join":
            if medium == "wifi":
                await core.wifi_join(url=url)
            elif medium == "bt":
                if not btaddr:
                    raise RuntimeError("BT addr required for Bluetooth join.")
                await core.bt_join(addr=btaddr, channel=btchan)
            else:
                await core.auto_join(wifi_url=url, bt_addr=btaddr, bt_channel=btchan)
        else:
            raise RuntimeError("Unknown mode.")

    async def send_message(self, text: str) -> None:
        async with self.lock:
            core = self.core
        if not core:
            raise RuntimeError("Not connected.")
        await core.send(text)


def create_app() -> FastAPI:
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(INDEX_HTML)

    @app.websocket("/ui")
    async def ui_socket(ws: WebSocket):
        await ws.accept()
        session = UISession(ws=ws, lock=asyncio.Lock())
        await ws.send_text(
            _json_dumps(
                {
                    "evt": "info",
                    "text": "Ready. Choose Host/Join and press Connect. "
                    "Tip: two browser tabs can act as two peers (host in one tab, join in another).",
                }
            )
        )
        try:
            while True:
                try:
                    raw = await ws.receive_text()
                except WebSocketDisconnect:
                    session.ws_closed = True
                    return

                try:
                    msg = json.loads(raw)
                    if not isinstance(msg, dict):
                        raise ValueError("Invalid message.")
                    cmd = msg.get("cmd")

                    if cmd == "connect":
                        mode = str(msg.get("mode") or "")
                        medium = str(msg.get("medium") or "auto")
                        passphrase = str(msg.get("pass") or os.environ.get("IRNCHAT_PASSPHRASE", ""))
                        if not passphrase:
                            raise RuntimeError("Passphrase required for privacy.")
                        bind = str(msg.get("bind") or "0.0.0.0")
                        port = int(msg.get("port") or 8765)
                        url = msg.get("url")
                        url = str(url) if url else None
                        btaddr = msg.get("btaddr")
                        btaddr = str(btaddr) if btaddr else None
                        btchan = int(msg.get("btchan") or 1)
                        await session.connect(
                            mode=mode,
                            medium=medium,
                            bind=bind,
                            port=port,
                            url=url,
                            btaddr=btaddr,
                            btchan=btchan,
                            passphrase=passphrase,
                        )
                    elif cmd == "send":
                        await session.send_message(str(msg.get("text") or ""))
                    elif cmd == "disconnect":
                        await session.disconnect()
                    else:
                        await session._send({"evt": "error", "text": "Unknown command."})
                except Exception as e:
                    await session._send({"evt": "error", "text": str(e)})
        finally:
            await session.cleanup()

    return app


def run_ui(*, host: str, port: int) -> None:
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")
