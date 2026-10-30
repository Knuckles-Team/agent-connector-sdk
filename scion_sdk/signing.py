"""Ed25519 signing and verification of published catalog datapoints.

A publisher signs each datapoint it advertises, and a consumer verifies the
signature against the publisher's public key before trusting the entry.
Datapoints are signed over canonical JSON (sorted keys, no whitespace).

The private key is a 32-byte seed read from ``ARD_SIGNING_PRIVATE_KEY`` as
base64 (standard or URL-safe), or passed explicitly. Without a configured
seed, a random key lives for the process only and :func:`is_configured`
reports ``False``, so the caller can advertise the catalog as unsigned.
Verification fails closed: any malformed key or signature returns ``False``.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from scion_sdk.config import setting

__all__ = [
    "SigningKeyError",
    "canonical",
    "is_configured",
    "public_key_b64",
    "sign_datapoint",
    "verify_datapoint",
]

SEED_SETTING = "ARD_SIGNING_PRIVATE_KEY"
_PROCESS_SEED = os.urandom(32)


class SigningKeyError(ValueError):
    """The configured signing seed is not 32 bytes of base64."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    text = text.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(text + "=" * (-len(text) % 4), validate=True)


def canonical(datapoint: Any) -> str:
    """Canonical JSON of ``datapoint``; a string is taken as already canonical."""
    if isinstance(datapoint, str):
        return datapoint
    return json.dumps(datapoint, sort_keys=True, separators=(",", ":"))


def _configured_seed() -> str:
    return str(setting(SEED_SETTING, default="") or "").strip()


def is_configured() -> bool:
    """Whether a deployment signing seed is configured."""
    return bool(_configured_seed())


def _seed_bytes(seed: bytes | None) -> bytes:
    if seed is not None:
        return seed
    configured = _configured_seed()
    if not configured:
        return _PROCESS_SEED
    try:
        return _b64d(configured)
    except ValueError as exc:
        raise SigningKeyError("signing seed is not base64") from exc


def _private_key(seed: bytes | None) -> ed25519.Ed25519PrivateKey:
    resolved = _seed_bytes(seed)
    if len(resolved) != 32:
        raise SigningKeyError("signing seed must be 32 bytes")
    return ed25519.Ed25519PrivateKey.from_private_bytes(resolved)


def public_key_b64(seed: bytes | None = None) -> str:
    """The base64url Ed25519 public key for ``seed`` (or the configured key)."""
    raw = (
        _private_key(seed)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return _b64e(raw)


def sign_datapoint(datapoint: Any, seed: bytes | None = None) -> str:
    """The base64url Ed25519 signature of ``datapoint``."""
    return _b64e(_private_key(seed).sign(canonical(datapoint).encode()))


def verify_datapoint(datapoint: Any, signature_b64: str, public_key: str) -> bool:
    """Whether ``signature_b64`` signs ``datapoint`` under ``public_key``."""
    if not signature_b64 or not public_key:
        return False
    try:
        key = ed25519.Ed25519PublicKey.from_public_bytes(_b64d(public_key))
        key.verify(_b64d(signature_b64), canonical(datapoint).encode())
    except Exception:
        return False
    return True
