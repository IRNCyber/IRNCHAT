from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .crypto import b64e


def default_identity_path() -> Path:
    """
    Persistent identity key location.

    This identity is an *anonymous cryptographic identifier* (not a username).
    It can be used for optional peer verification workflows.
    """

    base = os.environ.get("IRNCHAT_HOME")
    if base:
        return Path(base).expanduser().resolve() / "identity_ed25519"
    return Path.home() / ".irnchat" / "identity_ed25519"


@dataclass(frozen=True)
class Identity:
    priv: Ed25519PrivateKey

    @property
    def pub(self) -> Ed25519PublicKey:
        return self.priv.public_key()

    def public_bytes(self) -> bytes:
        return self.pub.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)

    def public_id(self) -> str:
        # Short public identifier; safe to display. Not inherently linkable to device names.
        raw = self.public_bytes()
        h = hashes.Hash(hashes.SHA256())
        h.update(b"irnchat-identity-v1")
        h.update(raw)
        digest = h.finalize()
        return b64e(digest[:10])

    def sign(self, data: bytes) -> bytes:
        return self.priv.sign(data)

    @staticmethod
    def verify(pub_raw: bytes, sig: bytes, data: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(pub_raw).verify(sig, data)
            return True
        except Exception:
            return False


def load_or_create_identity(path: Path | None = None) -> Identity:
    path = path or default_identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        raw = path.read_bytes()
        priv = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(priv, Ed25519PrivateKey):
            raise RuntimeError("identity key file is not an Ed25519 private key")
        return Identity(priv=priv)

    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    return Identity(priv=priv)

