from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64d(txt: str) -> bytes:
    padding = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode((txt + padding).encode("ascii"))


def _hkdf_32(ikm: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(ikm)


def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    h = hmac.HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


@dataclass(frozen=True)
class SessionKeys:
    tx_key: bytes
    rx_key: bytes


def make_ephemeral() -> tuple[X25519PrivateKey, bytes]:
    priv = X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes_raw()
    return priv, pub


def derive_session_keys(
    *,
    my_eph_priv: X25519PrivateKey,
    peer_eph_pub_raw: bytes,
    passphrase: str,
    role: str,
    transcript: bytes,
) -> SessionKeys:
    peer_pub = X25519PublicKey.from_public_bytes(peer_eph_pub_raw)
    shared = my_eph_priv.exchange(peer_pub)
    salt = _hkdf_32(
        passphrase.encode("utf-8"),
        salt=b"irnchat-psk-salt-v1",
        info=b"irnchat-psk-info-v1",
    )
    prk = _hkdf_32(shared, salt=salt, info=b"irnchat-handshake-v1")

    # Bind to the exact hello transcript so both sides agree on the same session.
    prk = _hkdf_32(prk, salt=_hmac_sha256(prk, transcript), info=b"irnchat-transcript-v1")

    a_to_b = _hkdf_32(prk, salt=b"irnchat-a2b-v1", info=b"irnchat-msg-key")
    b_to_a = _hkdf_32(prk, salt=b"irnchat-b2a-v1", info=b"irnchat-msg-key")
    if role == "initiator":
        return SessionKeys(tx_key=a_to_b, rx_key=b_to_a)
    if role == "responder":
        return SessionKeys(tx_key=b_to_a, rx_key=a_to_b)
    raise ValueError("role must be 'initiator' or 'responder'")


def encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> dict:
    aead = ChaCha20Poly1305(key)
    nonce = os.urandom(12)
    ct = aead.encrypt(nonce, plaintext, aad)
    return {"n": b64e(nonce), "c": b64e(ct)}


def decrypt(key: bytes, payload: dict, aad: bytes = b"") -> bytes:
    aead = ChaCha20Poly1305(key)
    nonce = b64d(payload["n"])
    ct = b64d(payload["c"])
    return aead.decrypt(nonce, ct, aad)

