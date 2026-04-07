from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .crypto import b64d, b64e, decrypt, derive_session_keys, encrypt, make_ephemeral
from .transports.link import TextLink
from cryptography.hazmat.primitives import hashes


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _transcript_bytes(hello_a: dict, hello_b: dict) -> bytes:
    return _json_dumps({"a": hello_a, "b": hello_b}).encode("utf-8")


def _session_id(transcript: bytes) -> str:
    h = hashes.Hash(hashes.SHA256())
    h.update(b"irnchat-session-id-v1")
    h.update(transcript)
    digest = h.finalize()
    return b64e(digest[:9])


class ReplayWindow:
    """
    Sliding window replay protection (last 64 sequence numbers).

    Accepts increasing sequence numbers. Also accepts out-of-order within the
    last 64 messages (useful for non-ordered transports), rejecting duplicates.
    """

    __slots__ = ("max_seen", "bitmap")

    def __init__(self) -> None:
        self.max_seen = -1
        self.bitmap = 0

    def check_and_mark(self, seq: int) -> bool:
        if seq < 0:
            return False
        if self.max_seen == -1:
            self.max_seen = seq
            self.bitmap = 1
            return True
        if seq > self.max_seen:
            shift = seq - self.max_seen
            if shift >= 64:
                self.bitmap = 1
            else:
                self.bitmap = ((self.bitmap << shift) & ((1 << 64) - 1)) | 1
            self.max_seen = seq
            return True

        delta = self.max_seen - seq
        if delta >= 64:
            return False
        bit = 1 << delta
        if self.bitmap & bit:
            return False
        self.bitmap |= bit
        return True


@dataclass(frozen=True)
class E2EESession:
    ws: TextLink
    role: str
    tx_key: bytes
    rx_key: bytes
    aad_base: bytes
    session_id: str
    _tx_seq: int
    _rx_window: ReplayWindow

    def pack_message(self, text: str) -> str:
        seq = self._tx_seq
        object.__setattr__(self, "_tx_seq", seq + 1)
        aad = self.aad_base + seq.to_bytes(8, "big")
        payload = encrypt(self.tx_key, text.encode("utf-8"), aad=aad)
        return _json_dumps({"t": "msg", "v": 1, "s": seq, "p": payload})

    def unpack_message(self, raw: str) -> str | None:
        try:
            obj = json.loads(raw)
        except Exception:
            return None
        if not isinstance(obj, dict) or obj.get("t") != "msg" or obj.get("v") != 1:
            return None
        try:
            seq = int(obj.get("s"))
        except Exception:
            return None
        if not self._rx_window.check_and_mark(seq):
            return None
        aad = self.aad_base + seq.to_bytes(8, "big")
        try:
            pt = decrypt(self.rx_key, obj["p"], aad=aad)
        except Exception:
            return None
        return pt.decode("utf-8", errors="replace")


async def handshake_initiator(ws, passphrase: str) -> E2EESession:
    priv, pub = make_ephemeral()
    hello = {"t": "hello", "v": 1, "eph": b64e(pub)}
    await ws.send(_json_dumps(hello))
    raw = await ws.recv()
    resp = json.loads(raw)
    if not isinstance(resp, dict) or resp.get("t") != "hello" or resp.get("v") != 1:
        raise RuntimeError("bad handshake response")
    peer_pub = b64d(str(resp.get("eph") or ""))

    transcript = _transcript_bytes(hello, resp)
    keys = derive_session_keys(
        my_eph_priv=priv,
        peer_eph_pub_raw=peer_pub,
        passphrase=passphrase,
        role="initiator",
        transcript=transcript,
    )
    return E2EESession(
        ws=ws,
        role="initiator",
        tx_key=keys.tx_key,
        rx_key=keys.rx_key,
        aad_base=transcript,
        session_id=_session_id(transcript),
        _tx_seq=0,
        _rx_window=ReplayWindow(),
    )


async def handshake_responder(ws, passphrase: str) -> E2EESession:
    raw = await ws.recv()
    hello = json.loads(raw)
    if not isinstance(hello, dict) or hello.get("t") != "hello" or hello.get("v") != 1:
        raise RuntimeError("bad handshake hello")
    peer_pub = b64d(str(hello.get("eph") or ""))

    priv, pub = make_ephemeral()
    resp = {"t": "hello", "v": 1, "eph": b64e(pub)}
    await ws.send(_json_dumps(resp))

    transcript = _transcript_bytes(hello, resp)
    keys = derive_session_keys(
        my_eph_priv=priv,
        peer_eph_pub_raw=peer_pub,
        passphrase=passphrase,
        role="responder",
        transcript=transcript,
    )
    return E2EESession(
        ws=ws,
        role="responder",
        tx_key=keys.tx_key,
        rx_key=keys.rx_key,
        aad_base=transcript,
        session_id=_session_id(transcript),
        _tx_seq=0,
        _rx_window=ReplayWindow(),
    )
