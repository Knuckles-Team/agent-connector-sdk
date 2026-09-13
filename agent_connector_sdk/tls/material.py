"""Private runtime files for certificate and key material."""

from __future__ import annotations

import atexit
import os
import re
import tempfile
from pathlib import Path

from agent_connector_sdk.config import setting
from agent_connector_sdk.tls.errors import TransportSecurityError

__all__ = ["MAX_PEM_BYTES", "MaterialStore", "default_runtime_root", "existing_path"]

#: Largest certificate or key file accepted, in bytes.
MAX_PEM_BYTES = 4_000_000

_CERTIFICATE_MARKER = "-----BEGIN CERTIFICATE-----"
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:ENCRYPTED |RSA |EC )?PRIVATE KEY-----")
_LIVE_PATHS: set[Path] = set()


def _remove(path: Path) -> None:
    path.unlink(missing_ok=True)
    _LIVE_PATHS.discard(path)


def _remove_live_paths() -> None:
    for path in tuple(_LIVE_PATHS):
        _remove(path)


atexit.register(_remove_live_paths)


def _has_marker(payload: str, kind: str) -> bool:
    has_certificate = _CERTIFICATE_MARKER in payload
    has_key = _PRIVATE_KEY_RE.search(payload) is not None
    return {
        "ca": has_certificate,
        "cert": has_certificate,
        "key": has_key,
        "bundle": has_certificate and has_key,
    }[kind]


def existing_path(value: object, *, directory: bool = False) -> Path:
    """Validate a configured certificate file or CA directory path."""
    rendered = str(value or "").strip()
    if not rendered:
        raise TransportSecurityError("tls_material_path_invalid")
    candidate = Path(rendered).expanduser()
    if not (candidate.is_dir() if directory else candidate.is_file()):
        raise TransportSecurityError("tls_material_unavailable")
    if not directory and candidate.stat().st_size > MAX_PEM_BYTES:
        raise TransportSecurityError("tls_material_too_large")
    return candidate


def default_runtime_root() -> Path:
    """``$XDG_RUNTIME_DIR/agent-connector-sdk/tls``, else a per-user temp directory."""
    runtime = setting("XDG_RUNTIME_DIR")
    base = (
        Path(runtime)
        if runtime
        else Path(tempfile.gettempdir()) / f"agent-connector-sdk-{os.getuid()}"
    )
    return base / "agent-connector-sdk" / "tls"


class MaterialStore:
    """Writes PEM payloads to mode-0600 files in a mode-0700 directory.

    Every file it writes is removed by :meth:`discard` and, failing that, at
    process exit.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or default_runtime_root()
        self.created: list[Path] = []

    def write(self, payload: str, *, kind: str) -> Path:
        """Write one ``ca``, ``cert``, ``key`` or ``bundle`` payload."""
        encoded = payload.encode("utf-8")
        if (
            not encoded
            or len(encoded) > MAX_PEM_BYTES
            or not _has_marker(payload, kind)
        ):
            raise TransportSecurityError("tls_material_invalid")
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._root.chmod(0o700)
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f"tls-{kind}-", suffix=".pem", dir=self._root
        )
        path = Path(raw_path)
        self.created.append(path)
        _LIVE_PATHS.add(path)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
        return path

    def discard(self) -> None:
        """Remove every file this store wrote."""
        for path in self.created:
            _remove(path)
        self.created.clear()
