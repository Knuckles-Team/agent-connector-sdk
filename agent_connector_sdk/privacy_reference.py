"""Stable, non-reversible references for durable identity fields."""

from __future__ import annotations

import hashlib
import hmac
import re
from functools import lru_cache
from typing import Any

from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.resolution import resolve_secret_reference

__all__ = ["persistence_reference"]

_REFERENCE_RE = re.compile(r"^pref_[a-z0-9_]+_[0-9a-f]{64}$")


@lru_cache(maxsize=1)
def _reference_key() -> bytes | None:
    reference = str(setting("PERSISTENCE_IDENTITY_HMAC_KEY_REF", "")).strip()
    return resolve_secret_reference(reference).encode("utf-8") if reference else None


def persistence_reference(kind: str, value: Any, *, namespace: str = "") -> str:
    """A stable, non-reversible ``pref_<kind>_<sha256>`` for a durable identity field.

    Keyed (HMAC-SHA-256) when ``PERSISTENCE_IDENTITY_HMAC_KEY_REF`` is set; an
    already-formed reference is returned unchanged; empty input returns ``""``.
    """
    text = str(value or "")
    if not text or _REFERENCE_RE.fullmatch(text):
        return text
    label = re.sub(r"[^a-z0-9_]+", "_", str(kind).lower()).strip("_") or "value"
    framed = b"\x00".join(
        (b"persistence-reference:v1", label.encode(), namespace.encode(), text.encode())
    )
    key = _reference_key()
    digest = (
        hmac.new(key, framed, hashlib.sha256).hexdigest()
        if key is not None
        else hashlib.sha256(framed).hexdigest()
    )
    return f"pref_{label}_{digest}"
