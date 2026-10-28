"""Bounded generic foreign-read receiver (SDK-SOURCE-INGEST-R004.37)."""

from __future__ import annotations

import asyncio
import time
import traceback
from types import SimpleNamespace
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
    ForeignReadSourceIdentity,
    NativeRequestResponseAdapter,
    OpenRequest,
    OpenResult,
    RequestResponseAdapter,
)

_DIGEST = "a" * 64
_SOURCE_IDENTITY = {
    "source_ref": "mcp://test",
    "source_revision": 1,
    "schema_digest": _DIGEST,
    "snapshot_ref": _DIGEST,
}


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
    assert (
        ForeignReadSourceIdentity.model_validate(_SOURCE_IDENTITY).source_revision == 1
    )
    assert ForeignReadMethod
    assert RequestResponseAdapter
    assert NativeRequestResponseAdapter


@pytest.mark.asyncio
async def test_generated_foreign_read_adapter_uses_the_canonical_sender(monkeypatch):
    calls: list[tuple[Any, Any, Any]] = []

    async def send_open(client: Any, params: Any, graph: Any) -> Any:
        calls.append((client, params, graph))
        return SimpleNamespace(payload={"ok": True})

    monkeypatch.setattr(
        foreign_read_module,
        "_generated_sender",
        lambda method: send_open if method == "ForeignReadOpen" else None,
    )
    client = object()
    adapter = NativeRequestResponseAdapter(client, graph="tenant:g")
    result = await adapter.request(
        "ForeignReadOpen", {"request": {"schema_version": 1}}
    )
    assert result.payload == {"ok": True}
    assert calls == [(client, {"request": {"schema_version": 1}}, "tenant:g")]


@pytest.mark.asyncio
async def test_generated_foreign_read_adapter_hides_sender_transport_failure(
    monkeypatch,
):
    async def broken(*_args: Any) -> Any:
        raise RuntimeError("https://secret.example.invalid response body")

    monkeypatch.setattr(
        foreign_read_module, "_generated_sender", lambda _method: broken
    )
    adapter = NativeRequestResponseAdapter(object())
    with pytest.raises(ForeignReadError) as caught:
        await adapter.request("ForeignReadOpen", {"request": {}})
    assert (caught.value.reason, caught.value.stage) == ("transport", "ForeignReadOpen")
    assert "secret.example" not in str(caught.value)


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.37")
@pytest.mark.asyncio
async def test_generated_foreign_read_adapter_uses_published_eg_client_sender() -> None:
    """Exercise the generated sender against the canonical client's ``_send`` seam."""

    try:
        import epistemic_graph.generated.query as generated_query
    except ImportError:
        pytest.skip("epistemic-graph generated query module is unavailable")
    if not hasattr(generated_query, "send_foreign_read_open"):
        pytest.skip("installed epistemic-graph does not publish foreign-read senders")

    approval = {
        "batch_id": "batch",
        "committed_version": 1,
        "connector": "connector",
        "contract_digest": _DIGEST,
        "head": {"binding_revision": 0, "pack_digest": "b" * 64},
        "registration": {
            "approval": "approved",
            "class_iri": "class",
            "connector": "connector",
            "contract_iri": "contract",
            "entity": "entity",
            "key_field": "id",
            "operation": "read",
            "resource_uri": "resource",
            "source_id": "source",
            "source_kind": "mcp_tool",
        },
        "schema_version": 1,
        "tenant_id": "tenant",
    }
    request = OpenRequest(
        schema_version=1,
        source_name="source",
        approval=approval,
        plan_digest="c" * 64,
        query_digest=_DIGEST,
        limits=_limits(max_rows=1, max_bytes=1_024, chunk_rows=1, chunk_bytes=1_024),
    )

    class CanonicalClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any, Any]] = []

        async def _send(
            self,
            method: str,
            params: Any,
            graph: Any,
            *,
            idempotency_key: Any = None,
        ) -> Any:
            assert idempotency_key is None
            self.calls.append((method, params, graph))
            return {
                "schema_version": 1,
                "execution": {"execution_id": 4, "query_digest": _DIGEST},
                "expires_at_ms": 4_000_000_000_000,
                "next_sequence": 0,
                "source_identity": _SOURCE_IDENTITY,
            }

    client = CanonicalClient()
    result = await NativeRequestResponseAdapter(client, graph="tenant:g").request(
        "ForeignReadOpen", {"request": request.model_dump(mode="json")}
    )

    assert result.payload["execution"]["execution_id"] == 4
    assert client.calls == [
        (
            "ForeignReadOpen",
            {"request": request.model_dump(mode="json")},
            "tenant:g",
        )
    ]


def test_foreign_read_rows_use_the_eg_msgpack_golden_fixture() -> None:
    from epistemic_graph.client import _pack_binary_msgpack

    rows = [
        ForeignReadRow(
            id="東京",
            columns={
                "unicode": "café",
                "float": 0.0,
                "array": [1, "é", True],
            },
            provenance=["source:✓"],
        )
    ]
    expected = _pack_binary_msgpack(
        [
            {
                "id": "東京",
                "score": None,
                "columns": {
                    "array": [1, "é", True],
                    "float": 0.0,
                    "unicode": "café",
                },
                "provenance": ["source:✓"],
            }
        ]
    )
    assert foreign_read_module._encoded_rows_bytes(rows) == len(expected)
    assert expected.hex() == (
        "9184a26964a6e69db1e4baaca573636f7265c0"
        "a7636f6c756d6e7383a561727261799301a2c3a9c3a5"
        "666c6f6174cb0000000000000000a7756e69636f6465"
        "a5636166c3a9aa70726f76656e616e636591aa736f7572"
        "63653ae29c93"
    )


def test_foreign_read_row_score_uses_the_eg_f32_wire_width() -> None:
    # ``ForeignReadRow.score`` is Rust ``Option<f32>``.  A Python float packed
    # as f64 would make the client and engine disagree on chunk_bytes.
    row = ForeignReadRow(id="row-1", score=0.5)
    assert foreign_read_module._encoded_rows_bytes([row]) == 43


def _limits(
    *,
    deadline_ms: int = 10_000,
    max_rows: int = 10,
    max_bytes: int = 4_096,
    chunk_rows: int = 2,
    chunk_bytes: int = 1_024,
) -> ForeignReadLimits:
    return ForeignReadLimits(
        max_rows=max_rows,
        max_bytes=max_bytes,
        chunk_rows=chunk_rows,
        chunk_bytes=chunk_bytes,
        deadline_ms=deadline_ms,
    )


def _open(
    *,
    deadline_ms: int = 10_000,
    max_rows: int = 10,
    max_bytes: int = 4_096,
    chunk_rows: int = 2,
    chunk_bytes: int = 1_024,
) -> OpenRequest:
    return OpenRequest(
        schema_version=1,
        source_name="connector/source",
        approval={"opaque": "generated-approval"},
        plan_digest=_DIGEST,
        query_digest=_DIGEST,
        limits=_limits(
            deadline_ms=deadline_ms,
            max_rows=max_rows,
            max_bytes=max_bytes,
            chunk_rows=chunk_rows,
            chunk_bytes=chunk_bytes,
        ),
    )


class _Adapter:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.calls.append((method, params))
        return next(self.responses)


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.37")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.38")
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
                "source_identity": _SOURCE_IDENTITY,
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
    with pytest.raises(ForeignReadError, match="digest"):
        await client.chunk(
            ChunkRequest(
                execution=opened.execution,
                sequence=0,
                source_identity={**_SOURCE_IDENTITY, "snapshot_ref": "b" * 64},
                rows=[ForeignReadRow(id="row-1")],
            )
        )
    assert [name for name, _ in adapter.calls] == ["ForeignReadOpen"]
    await client.chunk(
        ChunkRequest(
            source_identity=_SOURCE_IDENTITY,
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


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.38")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.39")
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
                "source_identity": _SOURCE_IDENTITY,
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
                "source_identity": _SOURCE_IDENTITY,
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


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.38")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.39")
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
                    "source_identity": _SOURCE_IDENTITY,
                }
            if method == "ForeignReadAbort" and phase != "abort":
                return {
                    "execution": execution,
                    "sequence": 0,
                    "reason": "cancelled",
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
                source_identity=_SOURCE_IDENTITY,
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
    expected_calls = ["ForeignReadOpen", f"ForeignRead{phase.title()}"]
    if phase != "abort":
        expected_calls.append("ForeignReadAbort")
    assert adapter.calls == expected_calls


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.38")
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
                "source_identity": _SOURCE_IDENTITY,
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


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.38")
@pytest.mark.asyncio
async def test_foreign_read_reaps_expired_handle_before_capacity(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(foreign_read_module, "_MAX_EXECUTIONS", 1)
    first_execution = {"execution_id": 14, "query_digest": _DIGEST}
    second_execution = {"execution_id": 15, "query_digest": _DIGEST}
    adapter = _Adapter(
        [
            {
                "schema_version": 1,
                "execution": first_execution,
                "expires_at_ms": int(time.time() * 1000) + 10_000,
                "next_sequence": 0,
                "source_identity": _SOURCE_IDENTITY,
            },
            {
                "schema_version": 1,
                "execution": second_execution,
                "expires_at_ms": int(time.time() * 1000) + 10_000,
                "next_sequence": 0,
                "source_identity": _SOURCE_IDENTITY,
            },
        ]
    )
    client = ForeignReadClient(adapter)
    first = await client.open(_open(deadline_ms=1))
    await asyncio.sleep(0.02)
    second = await client.open(_open())

    assert second.execution.execution_id == 15
    assert first.execution.execution_id not in client._executions
    assert first.execution.execution_id in client._tombstones
    assert [method for method, _ in adapter.calls] == [
        "ForeignReadOpen",
        "ForeignReadOpen",
    ]


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.39")
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


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.38")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.39")
@pytest.mark.asyncio
async def test_foreign_read_phase_timeout_aborts_remote_handle() -> None:
    execution = {"execution_id": 18, "query_digest": _DIGEST}

    class _Timeout:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def request(self, method: str, _params: dict[str, Any]) -> Any:
            self.calls.append(method)
            if method == "ForeignReadOpen":
                return {
                    "schema_version": 1,
                    "execution": execution,
                    "expires_at_ms": int(time.time() * 1000) + 10_000,
                    "next_sequence": 0,
                    "source_identity": _SOURCE_IDENTITY,
                }
            if method == "ForeignReadChunk":
                await asyncio.sleep(0.05)
            if method == "ForeignReadAbort":
                return {
                    "execution": execution,
                    "sequence": 0,
                    "reason": "deadline",
                }
            return {}

    adapter = _Timeout()
    client = ForeignReadClient(adapter)
    opened = await client.open(_open(deadline_ms=10))
    with pytest.raises(ForeignReadError, match="deadline"):
        await client.chunk(
            ChunkRequest(
                source_identity=_SOURCE_IDENTITY,
                execution=opened.execution,
                sequence=0,
                rows=[ForeignReadRow(id="row-1")],
            )
        )
    assert adapter.calls == [
        "ForeignReadOpen",
        "ForeignReadChunk",
        "ForeignReadAbort",
    ]
    assert not client._executions


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.38")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.39")
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
                "source_identity": _SOURCE_IDENTITY,
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
                source_identity=_SOURCE_IDENTITY,
                execution=opened.execution,
                sequence=0,
                rows=[ForeignReadRow(id="row-1", columns={"value": "x" * 2_000})],
            )
        )
    assert len(adapter.calls) == 1
    with pytest.raises(ForeignReadError, match="limit_exceeded"):
        await client.chunk(
            ChunkRequest(
                source_identity=_SOURCE_IDENTITY,
                execution=opened.execution,
                sequence=0,
                rows=[ForeignReadRow(id="row-1")],
            )
        )
    with pytest.raises(ForeignReadError, match="terminal"):
        await client.chunk(
            ChunkRequest(
                source_identity=_SOURCE_IDENTITY,
                execution=opened.execution,
                sequence=0,
                rows=[ForeignReadRow(id="row-1")],
            )
        )
    assert len(adapter.calls) == 3


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.38")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.39")
@pytest.mark.asyncio
async def test_foreign_read_checks_cumulative_limits_before_transport() -> None:
    execution = {"execution_id": 16, "query_digest": _DIGEST}
    adapter = _Adapter(
        [
            {
                "schema_version": 1,
                "execution": execution,
                "expires_at_ms": int(time.time() * 1000) + 10_000,
                "next_sequence": 0,
                "source_identity": _SOURCE_IDENTITY,
            },
            {
                "execution": execution,
                "sequence": 0,
                "accepted_rows": 1,
                "total_rows": 1,
                "total_bytes": 20,
                "next_sequence": 1,
            },
        ]
    )
    client = ForeignReadClient(adapter)
    opened = await client.open(_open(max_rows=1))
    row = ForeignReadRow(id="row-1")
    await client.chunk(
        ChunkRequest(
            source_identity=_SOURCE_IDENTITY,
            execution=opened.execution,
            sequence=0,
            rows=[row],
        )
    )
    calls_after_first_chunk = len(adapter.calls)
    with pytest.raises(ForeignReadError, match="limit_exceeded"):
        await client.chunk(
            ChunkRequest(
                source_identity=_SOURCE_IDENTITY,
                execution=opened.execution,
                sequence=1,
                rows=[row],
            )
        )
    assert len(adapter.calls) == calls_after_first_chunk

    byte_adapter = _Adapter(
        [
            {
                "schema_version": 1,
                "execution": {"execution_id": 17, "query_digest": _DIGEST},
                "expires_at_ms": int(time.time() * 1000) + 10_000,
                "next_sequence": 0,
                "source_identity": _SOURCE_IDENTITY,
            }
        ]
    )
    byte_client = ForeignReadClient(byte_adapter)
    byte_opened = await byte_client.open(_open(max_bytes=1))
    with pytest.raises(ForeignReadError, match="limit_exceeded"):
        await byte_client.chunk(
            ChunkRequest(
                source_identity=_SOURCE_IDENTITY,
                execution=byte_opened.execution,
                sequence=0,
                rows=[row],
            )
        )
    assert len(byte_adapter.calls) == 1


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.39")
@pytest.mark.asyncio
async def test_foreign_read_transport_errors_are_closed_and_unlinked() -> None:
    class _Leaky:
        async def request(self, _method: str, _params: dict[str, Any]) -> Any:
            raise RuntimeError("approval=secret-payload transport body")

    with pytest.raises(ForeignReadError) as caught:
        await ForeignReadClient(_Leaky()).open(_open())

    error = caught.value
    assert error.reason == "transport"
    assert str(error) == "transport"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "secret-payload" not in "".join(traceback.format_exception(error))


@pytest.mark.spec("SDK-SOURCE-INGEST-R004.37")
@pytest.mark.spec("SDK-SOURCE-INGEST-R004.39")
def test_foreign_read_dto_rejects_oversized_or_non_json_cells() -> None:
    with pytest.raises(ValueError, match="column value"):
        ForeignReadRow(id="row", columns={"value": "x" * (64 * 1024)})
    with pytest.raises(ValueError, match="provenance"):
        ForeignReadRow(id="row", provenance=("",))
