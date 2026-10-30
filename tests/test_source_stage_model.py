"""Stage declarations reject unsafe graphs before any source call."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import anyio
import pytest
from pydantic import ValidationError

from scion_sdk.runner.errors import RunnerConfigurationError
from scion_sdk.runner.stages import (
    StageDependency,
    StageDescriptor,
    StageLimits,
)
from scion_sdk.runner.syncing import SyncTarget, sync_stream


def _stage(stage_id: str, **overrides: Any) -> StageDescriptor:
    data: dict[str, Any] = {
        "stage_id": stage_id,
        "tenant": "tenant-a",
        "connector": "connector-a",
        "source": "source-a",
        "stream": stage_id,
        "manifest_digest": "sha256:" + "a" * 64,
        "dependencies": (),
        "admitted_limits": StageLimits(
            max_active_stages=2,
            page_rows=100,
            page_bytes=1024,
            queued_pages=1,
            deadline_ms=123456,
        ),
    }
    data.update(overrides)
    return StageDescriptor(**data)


def _target(
    stages: tuple[StageDescriptor, ...], *, tenant: str | None = "tenant-a"
) -> SyncTarget:
    return SyncTarget(
        connector="connector-a",
        sink=AsyncMock(),
        max_pages=1,
        tenant=tenant,
        stages=stages,
    )


@pytest.mark.spec("SCION-SOURCE-INGEST-R001.1")
def test_stage_graph_validates_authority_bounds_and_dependencies() -> None:
    first = _stage("first")
    second = _stage(
        "second",
        dependencies=(StageDependency(stage_id="first", receipt_id="receipt-a"),),
    )
    assert _target((first, second)).stages == (first, second)
    for invalid in (0, 2**31, True):
        with pytest.raises(ValidationError):
            StageLimits(
                max_active_stages=invalid,
                page_rows=100,
                page_bytes=1024,
                queued_pages=1,
                deadline_ms=123456,
            )
    with pytest.raises(ValidationError):
        _stage("first", tenant=" ")
    with pytest.raises(ValidationError):
        _stage("first", manifest_digest="mutable")
    with pytest.raises(ValueError, match="authority"):
        _target((first,), tenant=None)
    with pytest.raises(ValueError, match="authority"):
        _target((_stage("first", tenant="other"),))
    with pytest.raises(ValueError, match="duplicate stage identity"):
        _target((first, first))
    with pytest.raises(ValueError, match="duplicate stage stream"):
        _target((first, _stage("second", stream="first")))
    with pytest.raises(ValueError, match="unknown stage dependency"):
        _target(
            (
                _stage(
                    "first",
                    dependencies=(StageDependency(stage_id="absent", receipt_id="r"),),
                ),
            )
        )
    cyclic = _stage(
        "first", dependencies=(StageDependency(stage_id="second", receipt_id="r"),)
    )
    with pytest.raises(ValueError, match="cyclic"):
        _target((cyclic, second))


@pytest.mark.spec("SCION-SOURCE-INGEST-R001.1")
def test_stage_target_refuses_before_sequential_discovery() -> None:
    target = _target((_stage("first"),))
    adapter = AsyncMock()

    async def run() -> None:
        with pytest.raises(RunnerConfigurationError, match="unavailable"):
            await sync_stream(AsyncMock(), adapter, target)

    anyio.run(run)
    adapter.discover.assert_not_awaited()
    adapter.extract.assert_not_awaited()
    target.sink.source_status.assert_not_awaited()  # type: ignore[attr-defined]
