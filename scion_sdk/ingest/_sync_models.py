"""Errors, checkpoint state, budget and report models of the source runner."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from scion_sdk.ingest import source_budget as _budget
from scion_sdk.ingest.errors import IngestError
from scion_sdk.ingest.for_each import MAX_FAN_OUT

#: The KV namespace every source checkpoint lives in.
CHECKPOINT_NAMESPACE = "scion-sdk"


SyncState = Literal["completed", "partial", "failed"]


class SourceSyncError(IngestError):
    """A sync refused or failed; ``reason`` is a stable machine code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason


@runtime_checkable
class SourceSession(Protocol):
    """The tool calls a source sync needs from an MCP session."""

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """``tools/call``, returning the decoded result."""
        ...

    async def tool_is_read_only(self, name: str) -> bool:
        """Whether the server marks ``name`` read-only."""
        ...


class SourceCheckpointState(BaseModel):
    """The durable checkpoint of one source."""

    model_config = ConfigDict(extra="forbid")

    connector: str
    source_id: str
    cursor: str | None = None
    digests: dict[str, str] = Field(default_factory=dict)
    state: str = "never"
    records: int = 0
    last_job_id: str | None = None
    last_report: dict[str, Any] | None = None


class SourceSyncReport(BaseModel):
    """What one sync run did. Holds no credential and no record payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    connector: str
    source_id: str
    mode: str
    state: SyncState
    pages: int = 0
    records_seen: int = 0
    submitted: int = 0
    unchanged: int = 0
    batch_digests: tuple[str, ...] = ()
    cursor_before: str | None = None
    cursor_after: str | None = None
    reason: str | None = None
    #: The engine's refusal code (for example ``UNKNOWN_MAPPING_REFERENCE``)
    #: when ``reason`` is ``ingest_refused``; never a payload.
    engine_code: str | None = None


@dataclass(frozen=True)
class SyncBudget:
    """Bounds of one run: pages, records, batch size, seconds, tool retries."""

    max_pages: int = 50
    max_records: int = 5_000
    batch_size: int = 200
    max_seconds: float = 120.0
    max_fan_out: int = MAX_FAN_OUT
    attempts: int = 3
    backoff_initial_seconds: float = 0.5
    backoff_max_seconds: float = 8.0

    def __post_init__(self) -> None:
        _budget._validate_budget(self)


def checkpoint_key(connector: str, source_id: str) -> str:
    """The shared KV key of one source checkpoint."""
    return f"ingest-source/{connector}/{source_id}"


def record_digest(record: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of one record."""
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class KvSourceCheckpoints:
    """Source checkpoints in engine KV, shared scope, compare-and-swap writes."""

    def __init__(self, client: Any, *, namespace: str = CHECKPOINT_NAMESPACE) -> None:
        self._client = client
        self._namespace = namespace

    async def load(
        self, connector: str, source_id: str
    ) -> tuple[SourceCheckpointState, int]:
        """The checkpoint and its KV version; version 0 when none is stored."""
        from epistemic_graph.generated import storage

        entry = storage.decode_kv_get(
            await storage.send_kv_get(
                self._client,
                {
                    "namespace": self._namespace,
                    "key": checkpoint_key(connector, source_id),
                    "shared": True,
                },
            )
        )
        if entry is None:
            return SourceCheckpointState(connector=connector, source_id=source_id), 0
        state = SourceCheckpointState.model_validate_json(entry.value)
        return state, entry.version

    async def store(self, state: SourceCheckpointState, version: int) -> int:
        """Swap in ``state`` if the stored version is still ``version``.

        Raises:
            SourceSyncError: ``checkpoint_conflict`` when another writer moved it.
        """
        from epistemic_graph.generated import storage

        outcome = storage.decode_kv_cas(
            await storage.send_kv_cas(
                self._client,
                {
                    "namespace": self._namespace,
                    "key": checkpoint_key(state.connector, state.source_id),
                    "expected_version": version,
                    "new": state.model_dump_json().encode("utf-8"),
                    "shared": True,
                },
            )
        )
        if not outcome.swapped:
            raise SourceSyncError(
                "checkpoint_conflict", "another writer moved the source checkpoint"
            )
        return outcome.version
