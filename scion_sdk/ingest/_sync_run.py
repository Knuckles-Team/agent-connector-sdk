"""Mutable per-run state of the declared source runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scion_sdk.ingest.model import Entity, Relationship
from scion_sdk.ingest.sources import IngestSourceSpec

from ._sync_models import SourceCheckpointState, record_digest


@dataclass
class _Run:
    spec: IngestSourceSpec
    state: SourceCheckpointState
    version: int
    mode: str
    started: float
    pages: int = 0
    seen: int = 0
    submitted: int = 0
    unchanged: int = 0
    batches: list[str] = field(default_factory=list)
    pending: list[tuple[Entity, str]] = field(default_factory=list)
    pending_tool: str | None = None
    pending_edges: list[tuple[Entity | None, Relationship]] = field(
        default_factory=list
    )
    cursor: str | None = None
    cursor_before: str | None = None


def _is_unchanged(
    run: _Run, record_id: str, *, cursor: str | None, record: Any
) -> bool:
    spec = run.spec
    if (
        spec.incremental
        and run.mode != "full"
        and cursor is not None
        and run.state.cursor is not None
        and cursor <= run.state.cursor
    ):
        return True
    return run.state.digests.get(record_id) == record_digest(record)
