"""ASI-Bot — AES-256-GCM envelope encryption for exchange API credentials.

Design:
  - Master key: 32 random bytes, base64 in ASI_MASTER_KEY env var.
  - Per-record data key: 32 random bytes derived via HKDF-SHA256 from
    master key + per-record salt (16 bytes, stored alongside ciphertext).
  - Ciphertext: AES-256-GCM(data_key, nonce=12B, plaintext). GCM tag (16B)
    is appended automatically by cryptography.
  - Stored shape: {"v": 1, "salt": b64, "nonce": b64, "ct": b64}
  - Rotation path: bump "v", keep decryption support for old versions.

This is the same envelope pattern used by AWS KMS Encryption SDK, Google
Tink, and HashiCorp Vault — just with the KEK in env instead of HSM.
Suitable for production until you want to upgrade to a hosted KMS (then
only ASI_MASTER_KEY management changes; data_key derivation stays the same).
"""
from __future__ import annotations

import base64
import json
import os
import secrets
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _master_key() -> bytes:
    """Load the 32-byte master key from env, generate+persist if missing.

    In production the master key MUST survive restarts, so if it is not
    yet set we auto-generate one and write it to backend/.env so the ops
    workflow is "install, start, done" — same ergonomics as JWT_SECRET.
    """
    raw = os.environ.get("ASI_MASTER_KEY", "").strip()
    if raw:
        try:
            key = base64.b64decode(raw)
            if len(key) == 32:
                return key
        except Exception:
            pass
    # Auto-generate on first boot and persist.
    key = secrets.token_bytes(32)
    enc = base64.b64encode(key).decode()
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(env_path, "a") as f:
            f.write(f"\nASI_MASTER_KEY={enc}\n")
    except Exception:
        pass
    os.environ["ASI_MASTER_KEY"] = enc
    return key


def _derive_data_key(salt: bytes) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"asi-bot:v1")
    return hkdf.derive(_master_key())


def encrypt(plaintext: str) -> dict[str, Any]:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    dk = _derive_data_key(salt)
    ct = AESGCM(dk).encrypt(nonce, plaintext.encode(), None)
    return {
        "v": 1,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ct).decode(),
    }


def decrypt(record: dict[str, Any]) -> str:
    if not record or record.get("v") != 1:
        raise ValueError("Unsupported ciphertext version")
    salt = base64.b64decode(record["salt"])
    nonce = base64.b64decode(record["nonce"])
    ct = base64.b64decode(record["ct"])
    dk = _derive_data_key(salt)
    return AESGCM(dk).decrypt(nonce, ct, None).decode()


def mask(secret: str, keep: int = 4) -> str:
    """Mask a secret for safe display: 'abcd...wxyz' (first 4 + last 4)."""
    if not secret:
        return ""
    if len(secret) <= keep * 2:
        return "*" * len(secret)
    return f"{secret[:keep]}…{secret[-keep:]}"


def dumps(record: dict[str, Any]) -> str:
    return json.dumps(record, separators=(",", ":"))


def loads(blob: str) -> dict[str, Any]:
    return json.loads(blob)
