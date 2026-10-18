"""Sync one declared connector source into epistemic-graph (SDK-SOURCE-INGEST-R004.20-R004.23).

:class:`SourceSyncRunner` calls a source's declared read-only tools page by
page through a :class:`SourceSession`, maps each record to a typed
:class:`~agent_connector_sdk.ingest.model.Entity` whose provenance names the
connector, server and tool, and submits batches to the engine ``SourceIngest``
method through :class:`~agent_connector_sdk.ingest.service.KnowledgeIngest`.

The runner's own checkpoint (cursor, per-record content digests, last report)
lives in engine KV under the shared scope, keyed
``ingest-source/<connector>/<source>`` (:class:`KvSourceCheckpoints`). It is
written after each accepted batch with compare-and-swap, so a run that stops
part-way resumes from its last accepted batch, and a record whose digest is
unchanged is never submitted again.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import anyio
from pydantic import BaseModel, ConfigDict, Field

from agent_connector_sdk.ingest.errors import IngestError
from agent_connector_sdk.ingest.model import ChangeSet, Entity, IngestBinding
from agent_connector_sdk.ingest.sources import IngestSourceSpec
from agent_connector_sdk.runner.backoff import Backoff

__all__ = [
    "CHECKPOINT_NAMESPACE",
    "KvSourceCheckpoints",
    "SourceCheckpointState",
    "SourceSession",
    "SourceSyncError",
    "SourceSyncReport",
    "SourceSyncRunner",
    "SyncBudget",
    "checkpoint_key",
    "record_digest",
]

#: The KV namespace every source checkpoint lives in.
CHECKPOINT_NAMESPACE = "agent-connector-sdk"
_MAX_DIGESTS = 50_000
_SCALARS = (str, int, float, bool)

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


@dataclass(frozen=True)
class SyncBudget:
    """Bounds of one run: pages, records, batch size, seconds, tool retries."""

    max_pages: int = 50
    max_records: int = 5_000
    batch_size: int = 200
    max_seconds: float = 120.0
    attempts: int = 3
    backoff_initial_seconds: float = 0.5
    backoff_max_seconds: float = 8.0

    def __post_init__(self) -> None:
        if min(self.max_pages, self.max_records, self.batch_size, self.attempts) < 1:
            raise ValueError("every sync budget must be at least 1")


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


def _path(value: Any, path: str) -> Any:
    for part in [p for p in path.split(".") if p]:
        if isinstance(value, Mapping):
            value = value.get(part)
        elif (
            isinstance(value, Sequence)
            and not isinstance(value, str)
            and part.isdigit()
        ):
            index = int(part)
            value = value[index] if index < len(value) else None
        else:
            return None
    return value


def _records(result: Any, spec: IngestSourceSpec) -> list[Mapping[str, Any]]:
    found = _path(result, spec.records_path) if spec.records_path else result
    if found is None:
        return []
    if not isinstance(found, Sequence) or isinstance(found, str | bytes):
        raise SourceSyncError(
            "malformed_result", f"{spec.records_path or 'result'} is not a record list"
        )
    return [item for item in found if isinstance(item, Mapping)]


def _properties(record: Mapping[str, Any], spec: IngestSourceSpec) -> dict[str, Any]:
    kept: dict[str, Any] = {
        key: value
        for key, value in record.items()
        if isinstance(value, _SCALARS)
        or (isinstance(value, list) and all(isinstance(v, _SCALARS) for v in value))
    }
    for name, field_name in (("title", spec.title_field), ("text", spec.text_field)):
        value = record.get(field_name) if field_name else None
        if isinstance(value, _SCALARS):
            kept.setdefault(name, value)
    return kept


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
    cursor: str | None = None
    cursor_before: str | None = None


class SourceSyncRunner:
    """Run declared connector sources into epistemic-graph.

    Args:
        connector: The connector (manifest ``connector``) the sources belong to.
        server: The serving MCP server named in provenance.
        session: Where the source tools are called.
        ingest: Submits change sets (``KnowledgeIngest.submit`` shape).
        checkpoints: Loads and stores source checkpoints.
        budget: The bounds of one run.
        clock: Monotonic seconds (tests).
        sleep: Async sleep (tests).
    """

    def __init__(
        self,
        *,
        connector: str,
        server: str,
        session: SourceSession,
        ingest: Any,
        checkpoints: Any,
        budget: SyncBudget | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] = anyio.sleep,
    ) -> None:
        self._connector = connector
        self._server = server
        self._session = session
        self._ingest = ingest
        self._checkpoints = checkpoints
        self._budget = budget or SyncBudget()
        self._clock = clock
        self._sleep = sleep

    async def status(self, source_id: str) -> SourceCheckpointState:
        """The stored checkpoint of one source."""
        state, _ = await self._checkpoints.load(self._connector, source_id)
        return SourceCheckpointState.model_validate(state)

    async def sync(
        self,
        spec: IngestSourceSpec,
        *,
        mode: str = "incremental",
        job_id: str | None = None,
    ) -> SourceSyncReport:
        """Sync ``spec`` once within the budget; return the run report.

        Raises:
            SourceSyncError: ``not_read_only`` before any call, or
                ``checkpoint_conflict``. A tool failure after the retry budget
                is reported as a ``failed`` run, not raised.
        """
        for tool in spec.tools:
            if not await self._session.tool_is_read_only(tool):
                raise SourceSyncError(
                    "not_read_only", f"tool {tool!r} is not marked read-only"
                )
        state, version = await self._checkpoints.load(self._connector, spec.source_id)
        if mode == "full":
            state = state.model_copy(update={"cursor": None, "digests": {}})
        run = _Run(
            spec,
            state,
            version,
            mode,
            self._clock(),
            cursor=state.cursor,
            cursor_before=state.cursor,
        )
        final: SyncState = "completed"
        reason: str | None = None
        try:
            final = await self._sweep(run)
        except SourceSyncError as exc:
            if exc.reason == "checkpoint_conflict":
                raise
            final, reason = "failed", exc.reason
        report = self._report(run, final, reason)
        run.state = run.state.model_copy(
            update={
                "state": final,
                "last_job_id": job_id,
                "last_report": report.model_dump(mode="json"),
            }
        )
        run.version = await self._checkpoints.store(run.state, run.version)
        return report

    async def _sweep(self, run: _Run) -> SyncState:
        spec = run.spec
        for tool in spec.tools:
            page = spec.start_page
            while True:
                if self._exhausted(run):
                    await self._flush(run)
                    return "partial"
                result = await self._call(tool, self._arguments(spec, page))
                records = _records(result, spec)
                run.pages += 1
                for record in records:
                    await self._take(run, record, tool)
                if spec.pagination != "page" or len(records) < spec.page_size:
                    break
                page += 1
            await self._flush(run, tool=tool)
        return "completed"

    def _exhausted(self, run: _Run) -> bool:
        budget = self._budget
        return (
            run.pages >= budget.max_pages
            or run.seen >= budget.max_records
            or self._clock() - run.started >= budget.max_seconds
        )

    @staticmethod
    def _arguments(spec: IngestSourceSpec, page: int) -> dict[str, Any]:
        arguments: dict[str, Any] = dict(spec.arguments)
        if spec.pagination == "page" and spec.page_param:
            arguments[spec.page_param] = page
            if spec.page_size_param:
                arguments[spec.page_size_param] = spec.page_size
        return arguments

    async def _call(self, tool: str, arguments: Mapping[str, Any]) -> Any:
        budget = self._budget
        backoff = Backoff(budget.backoff_initial_seconds, budget.backoff_max_seconds)
        for attempt in range(budget.attempts):
            try:
                return await self._session.call_tool(tool, arguments)
            except Exception as exc:
                if attempt + 1 >= budget.attempts:
                    raise SourceSyncError(
                        "tool_failed", f"{tool} failed ({type(exc).__name__})"
                    ) from exc
                await self._sleep(backoff.next_delay())
        raise AssertionError("unreachable")

    async def _take(self, run: _Run, record: Mapping[str, Any], tool: str) -> None:
        spec = run.spec
        run.seen += 1
        raw_id = record.get(spec.id_field)
        if raw_id is None or not str(raw_id).strip():
            return
        record_id = str(raw_id)
        cursor_value = record.get(spec.cursor_field) if spec.cursor_field else None
        cursor = None if cursor_value is None else str(cursor_value)
        if (
            spec.incremental
            and run.mode != "full"
            and cursor is not None
            and run.state.cursor is not None
            and cursor <= run.state.cursor
        ):
            run.unchanged += 1
            return
        digest = record_digest(record)
        if run.state.digests.get(record_id) == digest:
            run.unchanged += 1
            return
        entity = Entity(
            id=record_id,
            node_type=spec.record_type,
            properties=_properties(record, spec),
            updated_at=cursor,
        )
        run.pending.append((entity, digest))
        if cursor is not None and (run.cursor is None or cursor > run.cursor):
            run.cursor = cursor
        if len(run.pending) >= self._budget.batch_size:
            await self._flush(run, tool=tool)

    async def _flush(self, run: _Run, *, tool: str | None = None) -> None:
        if not run.pending:
            return
        spec = run.spec
        binding = IngestBinding(
            connector=self._connector,
            stream=spec.source_id,
            server=self._server,
            tool=tool or spec.tools[0],
        )
        entities = tuple(entity for entity, _ in run.pending)
        try:
            receipt = await self._ingest.submit(
                binding, ChangeSet(entities=entities, cursor=run.cursor)
            )
        except SourceSyncError:
            raise
        except IngestError as exc:
            # The engine refused the batch (for example an unmapped record
            # type); nothing advances and the run reports the refusal.
            run.pending.clear()
            raise SourceSyncError("ingest_refused", str(exc)) from exc
        run.batches.append(str(receipt.batch_digest))
        digests = dict(run.state.digests)
        digests.update({entity.id: digest for entity, digest in run.pending})
        if len(digests) > _MAX_DIGESTS:
            digests = dict(list(digests.items())[-_MAX_DIGESTS:])
        run.submitted += len(run.pending)
        run.pending.clear()
        run.state = run.state.model_copy(
            update={
                "digests": digests,
                "cursor": run.cursor,
                "records": len(digests),
                "state": "running",
            }
        )
        run.version = await self._checkpoints.store(run.state, run.version)

    def _report(
        self, run: _Run, state: SyncState, reason: str | None
    ) -> SourceSyncReport:
        return SourceSyncReport(
            connector=self._connector,
            source_id=run.spec.source_id,
            mode=run.mode,
            state=state,
            pages=run.pages,
            records_seen=run.seen,
            submitted=run.submitted,
            unchanged=run.unchanged,
            batch_digests=tuple(run.batches),
            cursor_before=run.cursor_before,
            cursor_after=run.state.cursor,
            reason=reason,
        )
