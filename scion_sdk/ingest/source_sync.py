"""Sync one declared connector source into epistemic-graph (SCION-SOURCE-INGEST-R004.20-R004.23).

:class:`SourceSyncRunner` calls a source's declared read-only tools page by
page through a :class:`SourceSession`, maps each record to a typed
:class:`~scion_sdk.ingest.model.Entity` whose provenance names the
connector, server and tool, and submits batches to the engine ``SourceIngest``
method through :class:`~scion_sdk.ingest.service.KnowledgeIngest`.

The runner's own checkpoint (cursor, per-record content digests, last report)
lives in engine KV under the shared scope, keyed
``ingest-source/<connector>/<source>`` (:class:`KvSourceCheckpoints`). It is
written after each accepted batch with compare-and-swap, so a run that stops
part-way resumes from its last accepted batch, and a record whose digest is
unchanged is never submitted again.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import anyio

from scion_sdk.ingest import source_budget as _budget
from scion_sdk.ingest.model import (
    Entity,
    IngestBinding,
)
from scion_sdk.ingest.source_calls import _SourceCalls
from scion_sdk.ingest.sources import IngestSourceSpec

from ._sync_models import (
    CHECKPOINT_NAMESPACE,
    KvSourceCheckpoints,
    SourceCheckpointState,
    SourceSession,
    SourceSyncError,
    SourceSyncReport,
    SyncBudget,
    SyncState,
    checkpoint_key,
    record_digest,
)
from ._sync_records import _edges, _properties, _records
from ._sync_run import _is_unchanged, _Run

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

_MAX_DIGESTS = 50_000


class SourceSyncRunner(_budget._SourceBudgetMixin, _SourceCalls):
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

    _source_error = SourceSyncError

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
        sources: Mapping[str, IngestSourceSpec] | None = None,
    ) -> SourceSyncReport:
        """Sync ``spec`` once within the budget; return the run report.

        ``sources`` are the connector's declared sources, needed when ``spec``
        has ``for_each`` to find its parent. A missing parent, a cycle and a
        fan-out over ``budget.max_fan_out`` parent records are reported as a
        ``failed`` run with reason ``unknown_parent_source``,
        ``for_each_cycle`` and ``fan_out_exceeded``.

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
        engine_code: str | None = None
        try:
            final = await self._sweep(run, sources)
        except SourceSyncError as exc:
            final, reason, engine_code = await self._handle_sync_error(run, exc)
        report = self._report(run, final, reason).model_copy(
            update={"engine_code": engine_code}
        )
        run.state = run.state.model_copy(
            update={
                "state": final,
                "last_job_id": job_id,
                "last_report": report.model_dump(mode="json"),
            }
        )
        run.version = await self._checkpoints.store(run.state, run.version)
        return report

    async def _sweep(
        self, run: _Run, sources: Mapping[str, IngestSourceSpec] | None
    ) -> SyncState:
        spec = run.spec
        scopes: list[dict[str, Any]] = [{}]
        if spec.for_each is not None:
            argument = spec.for_each.argument
            scopes = [
                {argument: value}
                for value in await self._parent_values(run, spec, sources or {}, ())
            ]
        for scope in scopes:
            for tool in spec.tools:
                if not await self._sweep_tool(run, tool, scope, decode=_records):
                    return "partial"
        return "completed"

    async def _parent_values(
        self,
        run: _Run,
        spec: IngestSourceSpec,
        sources: Mapping[str, IngestSourceSpec],
        chain: tuple[str, ...],
    ) -> list[Any]:
        """The distinct values ``spec.for_each`` fans out over, in parent order."""
        link = spec.for_each
        if link is None:
            return []
        chain = (*chain, spec.source_id)
        parent = sources.get(link.source)
        if parent is None:
            raise SourceSyncError(
                "unknown_parent_source",
                f"source {spec.source_id!r} follows undeclared source {link.source!r}",
            )
        if link.source in chain:
            raise SourceSyncError(
                "for_each_cycle", f"sources {' -> '.join([*chain, link.source])}"
            )
        scopes: list[dict[str, Any]] = [{}]
        if parent.for_each is not None:
            scopes = [
                {parent.for_each.argument: value}
                for value in await self._parent_values(run, parent, sources, chain)
            ]
        values: list[Any] = []
        for scope in scopes:
            for tool in parent.tools:
                if not await self._session.tool_is_read_only(tool):
                    raise SourceSyncError(
                        "not_read_only", f"tool {tool!r} is not marked read-only"
                    )
                await self._parent_pages(
                    run,
                    parent,
                    tool,
                    scope=scope,
                    field=link.field,
                    values=values,
                    decode=_records,
                )
        return values

    async def _take(self, run: _Run, record: Mapping[str, Any], tool: str) -> None:
        spec = run.spec
        run.seen += 1
        raw_id = record.get(spec.id_field)
        if raw_id is None or not str(raw_id).strip():
            return
        record_id = str(raw_id)
        cursor_value = record.get(spec.cursor_field) if spec.cursor_field else None
        cursor = None if cursor_value is None else str(cursor_value)
        if _is_unchanged(run, record_id, cursor=cursor, record=record):
            run.unchanged += 1
            return
        entity = Entity(
            id=record_id,
            node_type=spec.record_type,
            properties=_properties(record, spec),
            updated_at=cursor,
        )
        run.pending_tool = tool
        run.pending.append((entity, record_digest(record)))
        run.pending_edges.extend(_edges(record_id, record, spec))
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
            tool=_budget._binding_tool(run, tool),
        )
        records = _budget._pending_records(run)
        receipt = await self._submit_pending(run, binding, records)
        run.batches.append(str(receipt.batch_digest))
        digests = dict(run.state.digests)
        digests.update({entity.id: digest for entity, digest in run.pending})
        if len(digests) > _MAX_DIGESTS:
            digests = dict(list(digests.items())[-_MAX_DIGESTS:])
        run.submitted += len(run.pending)
        run.pending.clear()
        run.pending_edges.clear()
        run.pending_tool = None
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
