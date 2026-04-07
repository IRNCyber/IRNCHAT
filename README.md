# IRNCHAT (prototype)

Local-range chat with end-to-end encryption (E2EE) over Wi‑Fi/LAN.

## What this does
- **Wi‑Fi/LAN medium:** WebSocket chat + UDP LAN discovery.
- **Bluetooth medium (Linux):** RFCOMM framed transport (no centralized servers).
- **Auto medium selection:** host can listen on both Wi‑Fi + Bluetooth and use whichever connects first.
- **E2EE:** ephemeral X25519 key agreement + HKDF + ChaCha20‑Poly1305 per message, plus replay protection (sequence window).
- **Local-range:** no cloud, no accounts; intended for the same LAN or local Docker network.

## Commands
- `irnchat wifi-host` / `irnchat wifi-join`
- `irnchat bluetooth host` / `irnchat bluetooth join` (Linux only)
- `irnchat auto-host` / `irnchat auto-join`
- `irnchat ui` (web UI)
- `irnchat gui` (desktop GUI)
- `irnchat selftest` (sanity test)

## What this does *not* fully solve
- **Full metadata anonymity:** on Wi‑Fi/IP networks, IP/MAC metadata is still visible to routers/APs. This app avoids sending usernames/device names and shows only a short session id, but it cannot hide network-layer metadata.
- **Signal-grade protocols:** this is not a Double Ratchet + prekey system.
- **Bluetooth in Docker Desktop (Windows/macOS):** typically not available.

## Run (without Docker)
```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e .
set IRNCHAT_PASSPHRASE=mysecret
irnchat wifi-host
```
On another machine (same LAN):
```bash
set IRNCHAT_PASSPHRASE=mysecret
irnchat wifi-join
```

If discovery doesn’t work, join directly:
```bash
irnchat wifi-join --url ws://192.168.1.10:8765/ws --pass mysecret
```

## Run (Bluetooth RFCOMM, Linux only)
Host (waits for a single peer):
```bash
export IRNCHAT_PASSPHRASE=mysecret
irnchat bluetooth host --channel 1
```
Join:
```bash
export IRNCHAT_PASSPHRASE=mysecret
irnchat bluetooth join --addr AA:BB:CC:DD:EE:FF --channel 1
```

## Auto medium (Wi‑Fi + Bluetooth)
Host:
```bash
export IRNCHAT_PASSPHRASE=mysecret
irnchat auto-host --wifi-port 8765 --bt-channel 1
```
Join (tries Bluetooth first only if `--bt-addr` is provided, otherwise uses Wi‑Fi):
```bash
export IRNCHAT_PASSPHRASE=mysecret
irnchat auto-join --bt-addr AA:BB:CC:DD:EE:FF
```

## Run (Docker)
```bash
docker compose up --build host
```
In a second terminal:
```bash
docker compose run --rm join
```

## Run with UI (recommended)
Start the UI (binds to `http://127.0.0.1:8000` by default):
```bash
set IRNCHAT_PASSPHRASE=mysecret
irnchat ui
```
Then open `http://127.0.0.1:8000` and choose Host/Join + Medium (Auto/Wi‑Fi/Bluetooth).

Docker UI:
```bash
docker compose up --build ui
```
Open `http://127.0.0.1:8000`.

## Desktop GUI (Tkinter)
```bash
set IRNCHAT_PASSPHRASE=mysecret
irnchat gui
```

## Security notes
- **Passphrase required:** set `--pass` / `IRNCHAT_PASSPHRASE` (no plaintext messages are sent).
- **Forward secrecy:** session keys are derived from ephemeral X25519.
- **Replay protection:** receiver rejects duplicates/out-of-window sequence numbers.
- This is still not a full Signal/Double‑Ratchet implementation.

## Unified architecture (high level)
```
┌──────────────────────┐
│     IRNCHAT CORE     │
│   (Python asyncio)   │
│----------------------│
│ Identity Layer       │
│ Encryption Engine    │
│ Wi‑Fi Module         │
│ Bluetooth Module     │
└─────────┬────────────┘
          │
  ┌───────┼─────────┬──────────────┐
  │       │         │              │
 Web UI   CLI Tool  Desktop GUI   Mobile UI
(FastAPI) (Python)  (Tkinter)   (PWA/Flutter)
```
- `src/irnchat/core.py`: IRNCHAT CORE (event bus + connect/send APIs)
- `src/irnchat/identity.py`: Identity layer (anonymous cryptographic identifier)
- `src/irnchat/session.py`: Encryption engine (handshake + E2EE + replay window)
- `src/irnchat/transports/wifi.py`: Wi‑Fi/LAN module (UDP discovery + WebSocket URLs)
- `src/irnchat/transports/bluetooth.py`: Bluetooth module (Linux RFCOMM)
- UIs:
  - Web UI: `src/irnchat/ui_server.py`
  - CLI: `src/irnchat/cli.py`
  - Desktop GUI (Tkinter): `src/irnchat/gui_tk.py`
