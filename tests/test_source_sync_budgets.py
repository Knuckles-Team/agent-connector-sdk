"""Declared source budgets refuse bad limits and stop bounded page calls."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from test_source_sync import ITEMS, _Checkpoints, _Ingest, _runner, _Session, _spec

from agent_connector_sdk.ingest.source_sync import SourceCheckpointState, SyncBudget
from agent_connector_sdk.runner.backoff import Backoff


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.53")
@pytest.mark.parametrize(
    "field", ["max_pages", "max_records", "batch_size", "attempts", "max_fan_out"]
)
@pytest.mark.parametrize("value", [0, -1, True, 1.5, float("nan"), float("inf")])
def test_count_budgets_require_positive_integers(field: str, value: Any) -> None:
    with pytest.raises(ValueError, match="positive integers"):
        SyncBudget(**{field: value})


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.53")
@pytest.mark.parametrize(
    "value", [0, -1, True, float("nan"), float("inf"), 10**1000, "1"]
)
def test_time_budget_and_backoff_are_finite(value: Any) -> None:
    with pytest.raises(ValueError):
        SyncBudget(max_seconds=value)
    with pytest.raises(ValueError):
        Backoff(value, 8.0)
    with pytest.raises(ValueError):
        Backoff(1.0, value)


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.53")
async def test_hung_source_call_returns_partial_without_progress() -> None:
    class HungSession(_Session):
        async def call_tool(self, name, arguments):
            self.calls.append(dict(arguments))
            await asyncio.sleep(10)
            raise AssertionError("source call should be cancelled")

    session, ingest, checkpoints = HungSession(ITEMS), _Ingest(), _Checkpoints()
    previous = SourceCheckpointState(
        connector="fixture-mcp",
        source_id="items",
        cursor="2025-01-01",
        digests={"old": "digest"},
    )
    checkpoints.stored[("fixture-mcp", "items")] = (previous, 1)
    report = await _runner(
        session, ingest, checkpoints, budget=SyncBudget(max_seconds=0.05)
    ).sync(_spec())
    state, _ = checkpoints.stored[("fixture-mcp", "items")]
    assert report.state == "partial" and report.reason == "deadline_exceeded"
    assert state.cursor == previous.cursor and state.digests == previous.digests
    assert len(session.calls) == 1 and ingest.batches == []


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.53")
async def test_deadline_keeps_prior_page_and_correct_tool_provenance() -> None:
    class TwoToolSession(_Session):
        async def call_tool(self, name, arguments):
            self.calls.append({"tool": name, **arguments})
            if name == "first":
                return {"data": []}
            if arguments["page"] == 1:
                return {"data": ITEMS[:2]}
            await asyncio.sleep(10)
            raise AssertionError("source call should be cancelled")

    session, ingest, checkpoints = TwoToolSession(ITEMS), _Ingest(), _Checkpoints()
    spec = _spec(tools=("first", "second"))
    report = await _runner(
        session, ingest, checkpoints, budget=SyncBudget(max_seconds=0.05, batch_size=10)
    ).sync(spec)
    state, _ = checkpoints.stored[("fixture-mcp", "items")]
    assert report.state == "partial" and report.reason == "deadline_exceeded"
    assert report.submitted == 2 and state.cursor == ITEMS[1]["updated"]
    assert len(ingest.batches) == 1 and ingest.batches[0][0].tool == "second"


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.53")
async def test_record_limit_never_partially_applies_a_page() -> None:
    session, ingest, checkpoints = _Session(ITEMS), _Ingest(), _Checkpoints()
    report = await _runner(
        session, ingest, checkpoints, budget=SyncBudget(max_records=3, batch_size=10)
    ).sync(_spec())
    state, _ = checkpoints.stored[("fixture-mcp", "items")]
    assert report.state == "partial" and report.records_seen == 2
    assert report.submitted == 2 and state.cursor == ITEMS[1]["updated"]
    assert len(ingest.batches) == 1
    assert [entity.id for entity in ingest.batches[0][1].entities] == ["1", "2"]


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.53")
async def test_retry_sleep_respects_remaining_source_deadline() -> None:
    from agent_connector_sdk.ingest.source_sync import SourceSyncRunner

    session, ingest, checkpoints = _Session(ITEMS), _Ingest(), _Checkpoints()
    session.failures = 10
    runner = SourceSyncRunner(
        connector="fixture-mcp",
        server="fixture-mcp",
        session=session,
        ingest=ingest,
        checkpoints=checkpoints,
        budget=SyncBudget(max_seconds=0.05, backoff_initial_seconds=1.0),
    )
    report = await runner.sync(_spec())
    assert report.state == "partial" and report.reason == "deadline_exceeded"
    assert len(session.calls) == 1 and ingest.batches == []


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.53")
async def test_partial_flush_refusal_does_not_advance_checkpoint() -> None:
    from agent_connector_sdk.ingest.errors import IngestError

    class RefusingIngest(_Ingest):
        async def submit(self, binding, changes):
            raise IngestError("UNKNOWN_MAPPING_REFERENCE")

    session, ingest, checkpoints = _Session(ITEMS), RefusingIngest(), _Checkpoints()
    report = await _runner(
        session, ingest, checkpoints, budget=SyncBudget(max_records=3, batch_size=10)
    ).sync(_spec())
    state, _ = checkpoints.stored[("fixture-mcp", "items")]
    assert report.state == "failed" and report.reason == "ingest_refused"
    assert report.engine_code == "UNKNOWN_MAPPING_REFERENCE"
    assert state.cursor is None and state.digests == {}


@pytest.mark.parametrize("pagination", ["cursor", "offset"])
async def test_source_sync_refuses_virtual_only_paging_before_a_tool_call(
    pagination: str,
) -> None:
    session, ingest, checkpoints = _Session(ITEMS), _Ingest(), _Checkpoints()
    spec = _spec(pagination=pagination, page_param=None)
    report = await _runner(session, ingest, checkpoints).sync(spec)
    assert report.state == "failed" and report.reason == "pagination_unsupported"
    assert session.calls == []
    assert ingest.batches == []


async def test_virtual_only_parent_paging_refuses_before_reading_parent() -> None:
    from test_for_each import _declaration
    from test_for_each import _Ingest as ParentIngest
    from test_for_each import _runner as parent_runner
    from test_for_each import _Session as ParentSession

    parent, child = _declaration()
    parent = parent.model_copy(update={"pagination": "cursor"})
    session, ingest = ParentSession(), ParentIngest()
    result = await parent_runner(session, ingest).sync(
        child, sources={parent.source_id: parent, child.source_id: child}
    )
    assert result.state == "failed" and result.reason == "pagination_unsupported"
    assert session.calls == [] and ingest.entities == []
