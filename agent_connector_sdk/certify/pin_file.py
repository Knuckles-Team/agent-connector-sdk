"""Durable single-file replacement for no-sync tool contract pins."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from agent_connector_sdk.certify.pin_journal import _sync_directory


def stage_contract_pins(path: Path, text: str) -> Path:
    """Write and sync a sibling temporary file before publishing pins."""
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.certify-", delete=False
    ) as stream:
        staging = Path(stream.name)
        try:
            stream.write(text.encode())
            stream.flush()
            os.fsync(stream.fileno())
        except OSError:
            staging.unlink(missing_ok=True)
            raise
        return staging


def _replace_contract_pins(staging: Path, path: Path) -> None:
    """Atomically publish a staged file and sync the containing directory."""
    if path.exists():
        staging.chmod(path.stat().st_mode & 0o777)
    os.replace(staging, path)
    _sync_directory(path.parent)
