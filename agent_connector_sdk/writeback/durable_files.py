"""Crash-safe JSON persistence shared by the file-backed write-back fixtures.

:class:`~agent_connector_sdk.writeback.durable_ledger.FileWriteBackLedger` and
:class:`~agent_connector_sdk.writeback.durable_transport.FileWriteBackTransport`
each need one thing from disk: a write that is either fully visible or not
visible at all, even when the writing process is killed immediately after the
write returns. ``os.replace`` is atomic on the same filesystem, so a reader
never observes a partially written file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = ["read_json", "write_json_atomic"]


def write_json_atomic(path: Path, payload: Any) -> None:
    """Replace ``path`` with ``payload`` in one atomic filesystem operation."""
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)


def read_json(path: Path) -> Any | None:
    """Return the parsed contents of ``path``, or ``None`` when absent."""
    if not path.exists():
        return None
    return json.loads(path.read_text())
