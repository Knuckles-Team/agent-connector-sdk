"""Source adapter conformance checks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_connector_sdk.contracts import SEAM_SCHEMA_VERSION, SourceRecord, SyncCursor
from agent_connector_sdk.ports.errors import MalformedSourceDataError
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.ports.source_adapter import SourceAdapter
from agent_connector_sdk.testing.results import ConformanceResult, SessionFactory

__all__ = [
    "Sweep",
    "check_capability_descriptor",
    "check_checkpoint_resume",
    "check_idempotent_rerun",
    "check_malformed_input_rejection",
    "check_pagination",
    "check_provenance_completeness",
    "run_source_adapter_suite",
    "sweep",
]


@dataclass(frozen=True)
class Sweep:
    """Everything one sweep produced."""

    records: tuple[SourceRecord, ...]
    cursor: SyncCursor | None
    pages: int
    exhausted: bool


async def sweep(
    adapter: SourceAdapter,
    session: McpSession,
    *,
    cursor: SyncCursor | None = None,
    max_pages: int = 1_000,
) -> Sweep:
    """Verify the source, then extract pages until exhausted or ``max_pages``."""
    await adapter.discover(session)
    records: list[SourceRecord] = []
    pages, exhausted = 0, False
    while pages < max_pages and not exhausted:
        page = await adapter.extract(session, cursor)
        records.extend(page.records)
        cursor, exhausted, pages = page.cursor, page.exhausted, pages + 1
    return Sweep(
        records=tuple(records), cursor=cursor, pages=pages, exhausted=exhausted
    )


def check_capability_descriptor(adapter: SourceAdapter) -> ConformanceResult:
    """The descriptor names the adapter kind, the seam version and pagination."""
    descriptor = adapter.describe()
    problems = [
        problem
        for problem, failed in (
            ("kind differs from adapter.kind", descriptor.kind != adapter.kind),
            (
                "unknown schema version",
                descriptor.schema_version != SEAM_SCHEMA_VERSION,
            ),
            ("no pagination declared", not descriptor.pagination),
        )
        if failed
    ]
    return ConformanceResult("capability-descriptor", not problems, ", ".join(problems))


async def check_pagination(
    adapter: SourceAdapter, sessions: SessionFactory
) -> ConformanceResult:
    """More than one page is drained, the sweep exhausts, and ids are unique."""
    async with sessions() as session:
        result = await sweep(adapter, session)
    ids = [record.record_id for record in result.records]
    problems = [
        problem
        for problem, failed in (
            ("fixture served a single page", result.pages < 2),
            ("sweep did not exhaust", not result.exhausted),
            ("duplicate record ids across pages", len(ids) != len(set(ids))),
        )
        if failed
    ]
    return ConformanceResult("pagination", not problems, ", ".join(problems))


async def check_checkpoint_resume(
    adapter: SourceAdapter, sessions: SessionFactory
) -> ConformanceResult:
    """Stopping after one page and resuming in a new session reproduces the sweep."""
    async with sessions() as session:
        full = await sweep(adapter, session)
    async with sessions() as session:
        first = await sweep(adapter, session, max_pages=1)
    async with sessions() as session:
        rest = await sweep(adapter, session, cursor=first.cursor)
    resumed = [record.content_digest for record in (*first.records, *rest.records)]
    same = resumed == [record.content_digest for record in full.records]
    passed = same and not first.exhausted and rest.exhausted
    return ConformanceResult(
        "checkpoint-resume", passed, "" if passed else "resumed sweep differs"
    )


async def check_idempotent_rerun(
    adapter: SourceAdapter, sessions: SessionFactory
) -> ConformanceResult:
    """Two sweeps of an unchanged source produce identical digests and cursors."""
    async with sessions() as session:
        first = await sweep(adapter, session)
    async with sessions() as session:
        second = await sweep(adapter, session)
    digests = (
        [r.content_digest for r in first.records],
        [r.content_digest for r in second.records],
    )
    same = digests[0] == digests[1] and first.cursor == second.cursor
    return ConformanceResult("idempotent-rerun", same, "" if same else "sweeps differ")


async def check_malformed_input_rejection(
    adapter: SourceAdapter, malformed_sessions: SessionFactory
) -> ConformanceResult:
    """A session serving malformed data makes extraction raise."""
    async with malformed_sessions() as session:
        try:
            await sweep(adapter, session, max_pages=1)
        except MalformedSourceDataError:
            return ConformanceResult("malformed-input-rejection", True)
    return ConformanceResult(
        "malformed-input-rejection", False, "malformed data was accepted"
    )


def check_provenance_completeness(records: Sequence[SourceRecord]) -> ConformanceResult:
    """Every record carries complete provenance naming its own id."""
    incomplete = [
        record.record_id
        for record in records
        if not all(record.provenance.model_dump().values())
        or record.record_id not in record.provenance.source_uri
    ]
    passed = bool(records) and not incomplete
    detail = "" if passed else f"no records or incomplete provenance: {incomplete[:5]}"
    return ConformanceResult("provenance-completeness", passed, detail)


async def run_source_adapter_suite(
    adapter: SourceAdapter, sessions: SessionFactory, malformed_sessions: SessionFactory
) -> list[ConformanceResult]:
    """Run every source adapter check."""
    async with sessions() as session:
        records = (await sweep(adapter, session)).records
    results = [check_capability_descriptor(adapter)]
    results.append(await check_pagination(adapter, sessions))
    results.append(await check_checkpoint_resume(adapter, sessions))
    results.append(await check_idempotent_rerun(adapter, sessions))
    results.append(await check_malformed_input_rejection(adapter, malformed_sessions))
    results.append(check_provenance_completeness(records))
    return results
