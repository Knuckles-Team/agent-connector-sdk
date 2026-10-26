"""Bounded generic foreign-read receiver (SDK-SOURCE-INGEST-R004.7)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

import agent_connector_sdk.adapters.foreign_read as foreign_read_module
from agent_connector_sdk.adapters.foreign_read import (
    FOREIGN_READ_SCHEMA_VERSION,
    AbortRequest,
    AbortResult,
    ChunkRequest,
    ChunkResult,
    CompleteRequest,
    CompleteResult,
    ForeignReadAbortRequest,
    ForeignReadAbortResult,
    ForeignReadChunkRequest,
    ForeignReadChunkResult,
    ForeignReadClient,
    ForeignReadCompleteRequest,
    ForeignReadCompleteResult,
    ForeignReadError,
    ForeignReadExecutionRef,
    ForeignReadLimits,
    ForeignReadMethod,
    ForeignReadOpenRequest,
    ForeignReadOpenResult,
    ForeignReadRow,
    OpenRequest,
    OpenResult,
    RequestResponseAdapter,
)

_DIGEST = "a" * 64


def test_foreign_read_public_aliases_and_contract_exports() -> None:
    assert FOREIGN_READ_SCHEMA_VERSION == 1
    assert AbortRequest is ForeignReadAbortRequest
    assert AbortResult is ForeignReadAbortResult
    assert ChunkRequest is ForeignReadChunkRequest
    assert ChunkResult is ForeignReadChunkResult
    assert CompleteRequest is ForeignReadCompleteRequest
    assert CompleteResult is ForeignReadCompleteResult
    assert OpenRequest is ForeignReadOpenRequest
    assert OpenResult is ForeignReadOpenResult
    assert ForeignReadMethod
    assert RequestResponseAdapter


def _limits(*, deadline_ms: int = 10_000) -> ForeignReadLimits:
    return ForeignReadLimits(
        max_rows=10,
        max_bytes=4_096,
        chunk_rows=2,
        chunk_bytes=1_024,
        deadline_ms=deadline_ms,
    )


def _open(*, deadline_ms: int = 10_000) -> OpenRequest:
    return OpenRequest(
        schema_version=1,
        source_name="connector/source",
        approval={"opaque": "generated-approval"},
        plan_digest=_DIGEST,
        query_digest=_DIGEST,
        limits=_limits(deadline_ms=deadline_ms),
    )


class _Adapter:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.calls.append((method, params))
        return next(self.responses)


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.1")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.2")
@pytest.mark.asyncio
async def test_foreign_read_lifecycle_uses_exact_methods_and_binds_digest() -> None:
    execution = {"execution_id": 7, "query_digest": _DIGEST}
    adapter = _Adapter(
        [
            {
                "schema_version": 1,
                "execution": execution,
                "expires_at_ms": int(time.time() * 1000) + 10_000,
                "next_sequence": 0,
            },
            {
                "execution": execution,
                "sequence": 0,
                "accepted_rows": 1,
                "total_rows": 1,
                "total_bytes": 20,
                "next_sequence": 1,
            },
            {
                "execution": execution,
                "sequence": 1,
                "total_rows": 1,
                "total_bytes": 20,
            },
        ]
    )
    client = ForeignReadClient(adapter)

    opened = await client.open(_open())
    await client.chunk(
        ChunkRequest(
            execution=opened.execution,
            sequence=0,
            rows=[ForeignReadRow(id="row-1", columns={"title": "Example"})],
        )
    )
    await client.complete(CompleteRequest(execution=opened.execution, sequence=1))

    assert [method for method, _ in adapter.calls] == [
        "ForeignReadOpen",
        "ForeignReadChunk",
        "ForeignReadComplete",
    ]
    open_params = adapter.calls[0][1]["request"]
    assert set(open_params) == {
        "schema_version",
        "source_name",
        "approval",
        "plan_digest",
        "query_digest",
        "limits",
    }
    chunk_params = adapter.calls[1][1]["request"]
    assert chunk_params["execution"] == execution
    assert chunk_params["sequence"] == 0
    assert chunk_params["rows"][0]["id"] == "row-1"


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.2")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.3")
@pytest.mark.asyncio
async def test_foreign_read_refuses_sequence_digest_and_terminal_replay() -> None:
    execution = {"execution_id": 9, "query_digest": _DIGEST}
    adapter = _Adapter(
        [
            {
                "schema_version": 1,
                "execution": execution,
                "expires_at_ms": int(time.time() * 1000) + 10_000,
                "next_sequence": 0,
            },
            {
                "execution": execution,
                "sequence": 0,
                "total_rows": 0,
                "total_bytes": 0,
            },
        ]
    )
    client = ForeignReadClient(adapter)
    opened = await client.open(_open())

    with pytest.raises(ForeignReadError, match="sequence"):
        await client.complete(CompleteRequest(execution=opened.execution, sequence=1))
    assert len(adapter.calls) == 1

    await client.complete(CompleteRequest(execution=opened.execution, sequence=0))
    assert not client._executions
    assert opened.execution.execution_id in client._tombstones
    with pytest.raises(ForeignReadError, match="terminal"):
        await client.complete(CompleteRequest(execution=opened.execution, sequence=0))
    assert len(adapter.calls) == 2

    with pytest.raises(ForeignReadError, match="unknown_execution"):
        await client.abort(
            AbortRequest(
                execution=ForeignReadExecutionRef(
                    execution_id=99, query_digest=_DIGEST
                ),
                sequence=0,
                reason="cancelled",
            )
        )

    cancel_execution = {"execution_id": 10, "query_digest": _DIGEST}
    cancel_adapter = _Adapter(
        [
            {
                "schema_version": 1,
                "execution": cancel_execution,
                "expires_at_ms": int(time.time() * 1000) + 10_000,
                "next_sequence": 0,
            },
            {
                "execution": cancel_execution,
                "sequence": 0,
                "reason": "cancelled",
            },
        ]
    )
    cancel_client = ForeignReadClient(cancel_adapter)
    cancel_opened = await cancel_client.open(_open())
    cancelled = await cancel_client.cancel(cancel_opened.execution)
    assert cancelled.reason == "cancelled"
    assert [method for method, _ in cancel_adapter.calls] == [
        "ForeignReadOpen",
        "ForeignReadAbort",
    ]


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.2")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.3")
@pytest.mark.parametrize("phase", ["chunk", "complete", "abort"])
@pytest.mark.asyncio
async def test_foreign_read_cancelled_phase_terminalizes_handle(phase: str) -> None:
    execution = {"execution_id": 12, "query_digest": _DIGEST}

    class _Blocking:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.calls: list[str] = []

        async def request(self, method: str, _params: dict[str, Any]) -> Any:
            self.calls.append(method)
            if method == "ForeignReadOpen":
                return {
                    "schema_version": 1,
                    "execution": execution,
                    "expires_at_ms": int(time.time() * 1000) + 10_000,
                    "next_sequence": 0,
                }
            if method == f"ForeignRead{phase.title()}":
                self.started.set()
                await asyncio.Event().wait()
            return {}

    adapter = _Blocking()
    client = ForeignReadClient(adapter)
    opened = await client.open(_open())
    if phase == "chunk":
        operation = client.chunk(
            ChunkRequest(
                execution=opened.execution,
                sequence=0,
                rows=[ForeignReadRow(id="row-1")],
            )
        )
    elif phase == "complete":
        operation = client.complete(
            CompleteRequest(execution=opened.execution, sequence=0)
        )
    else:
        operation = client.abort(
            AbortRequest(
                execution=opened.execution,
                sequence=0,
                reason="cancelled",
            )
        )
    task = asyncio.create_task(operation)
    await adapter.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ForeignReadError, match="terminal"):
        await client.complete(CompleteRequest(execution=opened.execution, sequence=0))
    assert not client._executions
    assert adapter.calls == ["ForeignReadOpen", f"ForeignRead{phase.title()}"]


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.2")
@pytest.mark.asyncio
async def test_foreign_read_open_reserves_concurrent_capacity(monkeypatch: Any) -> None:
    monkeypatch.setattr(foreign_read_module, "_MAX_EXECUTIONS", 1)
    execution = {"execution_id": 13, "query_digest": _DIGEST}

    class _SlowOpen:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def request(self, _method: str, _params: dict[str, Any]) -> Any:
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return {
                "schema_version": 1,
                "execution": execution,
                "expires_at_ms": int(time.time() * 1000) + 10_000,
                "next_sequence": 0,
            }

    adapter = _SlowOpen()
    client = ForeignReadClient(adapter)
    first = asyncio.create_task(client.open(_open()))
    await adapter.started.wait()
    with pytest.raises(ForeignReadError, match="limit_exceeded"):
        await client.open(_open())
    assert adapter.calls == 1
    adapter.release.set()
    await first


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.3")
@pytest.mark.asyncio
async def test_foreign_read_timeout_and_malformed_response_fail_closed() -> None:
    class _Slow:
        async def request(self, _method: str, _params: dict[str, Any]) -> Any:
            await asyncio.sleep(0.02)
            return {}

    with pytest.raises(ForeignReadError, match="deadline"):
        await ForeignReadClient(_Slow()).open(_open(deadline_ms=1))

    class _Malformed:
        async def request(self, _method: str, _params: dict[str, Any]) -> Any:
            return {"schema_version": 1, "execution": {}}

    with pytest.raises(ForeignReadError, match="invalid_response"):
        await ForeignReadClient(_Malformed()).open(_open())


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.2")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.3")
@pytest.mark.asyncio
async def test_foreign_read_enforces_per_chunk_bytes() -> None:
    execution = {"execution_id": 11, "query_digest": _DIGEST}
    adapter = _Adapter(
        [
            {
                "schema_version": 1,
                "execution": execution,
                "expires_at_ms": int(time.time() * 1000) + 10_000,
                "next_sequence": 0,
            },
            {
                "execution": execution,
                "sequence": 0,
                "accepted_rows": 1,
                "total_rows": 1,
                "total_bytes": 1_025,
                "next_sequence": 1,
            },
        ]
    )
    client = ForeignReadClient(adapter)
    opened = await client.open(_open())
    with pytest.raises(ForeignReadError, match="limit_exceeded"):
        await client.chunk(
            ChunkRequest(
                execution=opened.execution,
                sequence=0,
                rows=[ForeignReadRow(id="row-1", columns={"value": "x" * 2_000})],
            )
        )
    assert len(adapter.calls) == 1
    with pytest.raises(ForeignReadError, match="limit_exceeded"):
        await client.chunk(
            ChunkRequest(
                execution=opened.execution,
                sequence=0,
                rows=[ForeignReadRow(id="row-1")],
            )
        )
    with pytest.raises(ForeignReadError, match="terminal"):
        await client.chunk(
            ChunkRequest(
                execution=opened.execution,
                sequence=0,
                rows=[ForeignReadRow(id="row-1")],
            )
        )
    assert len(adapter.calls) == 2


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.1")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.7.3")
def test_foreign_read_dto_rejects_oversized_or_non_json_cells() -> None:
    with pytest.raises(ValueError, match="column value"):
        ForeignReadRow(id="row", columns={"value": "x" * (64 * 1024)})
    with pytest.raises(ValueError, match="provenance"):
        ForeignReadRow(id="row", provenance=("",))
