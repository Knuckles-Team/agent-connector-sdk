"""PKCE and out-of-band code-file helpers for the browser OAuth flow."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import secrets


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge using SHA-256 (S256)."""
    verifier = secrets.token_urlsafe(64)
    sha256_hash = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(sha256_hash).decode("utf-8").rstrip("=")
    return verifier, challenge


def _consume_code_file(path: str) -> str | None:
    """The code written to ``path`` (removing the file), or ``None`` if absent/empty."""
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        code = handle.read().strip()
    if not code:
        return None
    with contextlib.suppress(OSError):
        os.remove(path)
    return code
