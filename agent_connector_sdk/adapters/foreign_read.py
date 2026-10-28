"""Typed, bounded receiver for EG's generic foreign-read lifecycle.

The engine owns approval, tenant/actor authority, source registration and the
opaque execution handle. This module owns a typed port matching the EG DTO
source and short-lived client-side sequence/deadline checks. The concrete EG
adapter below resolves the generated sender lazily so an SDK wheel can be
installed before the matching engine wheel; an unpublished sender fails closed
at call time. It sends each phase through an authenticated client, never
creating authority or opening a connector itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

__all__ = [
    "FOREIGN_READ_SCHEMA_VERSION",
    "AbortRequest",
    "AbortResult",
    "ChunkRequest",
    "ChunkResult",
    "CompleteRequest",
    "CompleteResult",
    "ForeignReadAbortRequest",
    "ForeignReadAbortResult",
    "ForeignReadChunkRequest",
    "ForeignReadChunkResult",
    "ForeignReadClient",
    "ForeignReadCompleteRequest",
    "ForeignReadCompleteResult",
    "ForeignReadError",
    "ForeignReadExecutionRef",
    "ForeignReadLimits",
    "ForeignReadMethod",
    "ForeignReadOpenRequest",
    "ForeignReadOpenResult",
    "ForeignReadRow",
    "ForeignReadSourceIdentity",
    "NativeRequestResponseAdapter",
    "OpenRequest",
    "OpenResult",
    "RequestResponseAdapter",
]

FOREIGN_READ_SCHEMA_VERSION = 1
_MAX_ID_BYTES = 64 * 1024
_MAX_COLUMNS = 128
_MAX_COLUMN_NAME_BYTES = 256
_MAX_COLUMN_VALUE_BYTES = 64 * 1024
_MAX_PROVENANCE_ITEMS = 32
_MAX_PROVENANCE_BYTES = 4 * 1024
_MAX_EXECUTIONS = 1024
_U64_MAX = 2**64 - 1
_ABORT_CLEANUP_TIMEOUT_S = 1.0

ForeignReadMethod = Literal[
    "ForeignReadOpen",
    "ForeignReadChunk",
    "ForeignReadComplete",
    "ForeignReadAbort",
]
Digest256 = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[0-9a-f]{64}$",
        min_length=64,
        max_length=64,
    ),
]


class ForeignReadError(RuntimeError):
    """A refusal at the typed foreign-read boundary.

    The error intentionally carries only a closed reason and stage.  Request
    values, approval contents and transport details never enter diagnostics.
    """

    _REASONS = frozenset(
        {
            "invalid_request",
            "invalid_response",
            "schema_mismatch",
            "transport",
            "deadline",
            "expired",
            "sequence",
            "digest",
            "limit_exceeded",
            "unknown_execution",
            "terminal",
            "cancelled",
        }
    )

    def __init__(self, reason: str, stage: str = "client") -> None:
        if reason not in self._REASONS:
            reason = "transport"
        self.reason = reason
        self.stage = stage
        super().__init__(reason)


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


def _bounded_u64() -> Any:
    return Field(ge=0, le=_U64_MAX)


class ForeignReadLimits(_Strict):
    """The exact finite limits accepted by EG ``ForeignReadLimits``."""

    max_rows: int = Field(gt=0, le=250_000)
    max_bytes: int = Field(gt=0, le=64 * 1024 * 1024)
    chunk_rows: int = Field(gt=0, le=16_384)
    chunk_bytes: int = Field(gt=0, le=4 * 1024 * 1024)
    deadline_ms: int = Field(gt=0, le=60_000)


class ForeignReadExecutionRef(_Strict):
    """Server-owned opaque execution identity bound to one query digest."""

    execution_id: int = _bounded_u64()
    query_digest: Digest256


class ForeignReadSourceIdentity(_Strict):
    """Source identity issued by EG from the approved pack and current head."""

    source_ref: str = Field(min_length=1, max_length=_MAX_ID_BYTES)
    source_revision: int = _bounded_u64()
    schema_digest: Digest256
    snapshot_ref: Digest256

    @model_validator(mode="after")
    def _source_ref_bytes(self) -> ForeignReadSourceIdentity:
        if len(self.source_ref.encode()) > _MAX_ID_BYTES:
            raise ValueError("foreign-read source reference is too large")
        return self


class ForeignReadRow(_Strict):
    """One mapped row in EG's existing ``ForeignRows`` value currency."""

    id: str = Field(min_length=1, max_length=_MAX_ID_BYTES)
    score: float | None = Field(default=None, allow_inf_nan=False)
    columns: dict[str, Any] = Field(default_factory=dict)
    provenance: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bounded_cells(self) -> ForeignReadRow:
        if len(self.id.encode()) > _MAX_ID_BYTES:
            raise ValueError("foreign-read row id is too large")
        if len(self.columns) > _MAX_COLUMNS:
            raise ValueError("foreign-read row has too many columns")
        for name, value in self.columns.items():
            if not name or len(name.encode()) > _MAX_COLUMN_NAME_BYTES:
                raise ValueError("foreign-read column name is too large")
            try:
                encoded = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode()
            except (TypeError, ValueError) as exc:
                raise ValueError("foreign-read column value is not JSON") from exc
            if len(encoded) > _MAX_COLUMN_VALUE_BYTES:
                raise ValueError("foreign-read column value is too large")
        if len(self.provenance) > _MAX_PROVENANCE_ITEMS or any(
            not item or len(item.encode()) > _MAX_PROVENANCE_BYTES
            for item in self.provenance
        ):
            raise ValueError("foreign-read provenance is invalid")
        return self


class ForeignReadOpenRequest(_Strict):
    """Exact EG ``ForeignReadOpenRequest``; approval remains an EG-owned DTO."""

    schema_version: int = Field(ge=0, le=65_535)
    source_name: str = Field(min_length=1, max_length=_MAX_ID_BYTES)
    approval: Any
    plan_digest: Digest256
    query_digest: Digest256
    limits: ForeignReadLimits

    @model_validator(mode="after")
    def _approval_is_opaque_dto(self) -> ForeignReadOpenRequest:
        # Do not copy or reinterpret ConnectorPackSourceApprovalResult here;
        # generated Pydantic models and mapping-shaped generated DTOs are both
        # accepted, while a scalar cannot be a producer approval record.
        if self.approval is None or (
            not isinstance(self.approval, Mapping)
            and not hasattr(self.approval, "model_dump")
        ):
            raise ValueError("foreign-read approval must be a generated DTO")
        if len(self.source_name.encode()) > _MAX_ID_BYTES:
            raise ValueError("foreign-read source name is too large")
        return self


class ForeignReadOpenResult(_Strict):
    schema_version: int = Field(ge=0, le=65_535)
    execution: ForeignReadExecutionRef
    expires_at_ms: int = _bounded_u64()
    next_sequence: int = _bounded_u64()
    source_identity: ForeignReadSourceIdentity


class ForeignReadChunkRequest(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()
    source_identity: ForeignReadSourceIdentity
    rows: list[ForeignReadRow] = Field(min_length=1, max_length=16_384)

    @model_validator(mode="after")
    def _bounded_wire_rows(self) -> ForeignReadChunkRequest:
        try:
            encoded = _encoded_rows_bytes(self.rows)
        except ValueError:
            raise ValueError("foreign-read rows are not encodable") from None
        if encoded > 4 * 1024 * 1024:
            raise ValueError("foreign-read chunk rows exceed the EG byte cap")
        return self


class ForeignReadChunkResult(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()
    accepted_rows: int = Field(ge=0, le=2**32 - 1)
    total_rows: int = _bounded_u64()
    total_bytes: int = _bounded_u64()
    next_sequence: int = _bounded_u64()


class ForeignReadCompleteRequest(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()


class ForeignReadCompleteResult(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()
    total_rows: int = _bounded_u64()
    total_bytes: int = _bounded_u64()


class ForeignReadAbortRequest(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()
    reason: str = Field(min_length=1, max_length=_MAX_ID_BYTES)

    @model_validator(mode="after")
    def _reason_bytes(self) -> ForeignReadAbortRequest:
        if len(self.reason.encode()) > _MAX_ID_BYTES:
            raise ValueError("foreign-read abort reason is too large")
        return self


class ForeignReadAbortResult(_Strict):
    execution: ForeignReadExecutionRef
    sequence: int = _bounded_u64()
    reason: str = Field(min_length=1, max_length=_MAX_ID_BYTES)


# Short names mirror the four method signatures in the cross-owner contract.
OpenRequest = ForeignReadOpenRequest
OpenResult = ForeignReadOpenResult
ChunkRequest = ForeignReadChunkRequest
ChunkResult = ForeignReadChunkResult
CompleteRequest = ForeignReadCompleteRequest
CompleteResult = ForeignReadCompleteResult
AbortRequest = ForeignReadAbortRequest
AbortResult = ForeignReadAbortResult


@runtime_checkable
class RequestResponseAdapter(Protocol):
    """The already-authenticated, one-request/one-response engine seam."""

    async def request(
        self, method: ForeignReadMethod, params: Mapping[str, Any]
    ) -> Any:
        """Send one generated method request without adding authority fields."""
        ...


_GENERATED_SENDERS: dict[ForeignReadMethod, str] = {
    "ForeignReadOpen": "send_foreign_read_open",
    "ForeignReadChunk": "send_foreign_read_chunk",
    "ForeignReadComplete": "send_foreign_read_complete",
    "ForeignReadAbort": "send_foreign_read_abort",
}


def _generated_sender(method: ForeignReadMethod) -> Any:
    """Resolve one published EG sender without making it an import-time dep."""

    try:
        module = importlib.import_module("epistemic_graph.generated.query")
        sender = getattr(module, _GENERATED_SENDERS[method], None)
    except (ImportError, KeyError):
        sender = None
    if sender is None:
        raise ForeignReadError("schema_mismatch", method)
    return sender


class NativeRequestResponseAdapter:
    """Bind the generic receiver to EG's generated, authenticated client.

    The generated sender owns request-envelope construction, graph selection and
    the client's verified authority context. Keeping that binding in the SDK
    means Arbora's fleet executor only supplies its already-routed EG client;
    it never reaches into ``client._send`` or manufactures an engine request.
    """

    def __init__(self, client: Any, *, graph: str | None = None) -> None:
        self._client = client
        self._graph = graph

    async def request(
        self, method: ForeignReadMethod, params: Mapping[str, Any]
    ) -> Any:
        sender = _generated_sender(method)
        try:
            # ``params`` already contains the typed receiver's single ``request``
            # member. The generated function validates that shape before sending.
            return await sender(self._client, dict(params), self._graph)
        except ForeignReadError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not expose transport URLs, engine error bodies or approval data.
            raise ForeignReadError("transport", method) from None


@dataclass
class _Execution:
    request: OpenRequest
    opened: OpenResult
    deadline_at: float
    expected_sequence: int
    lock: asyncio.Lock
    total_rows: int = 0
    total_bytes: int = 0
    terminal: bool = False


def _payload(value: Any) -> Any:
    payload = getattr(value, "payload", value)
    return payload


def _wire(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _encoded_rows_bytes(rows: Sequence[ForeignReadRow]) -> int:
    """Return the EG client codec size for the named Rust row sequence.

    The engine's Rust boundary uses ``rmp_serde::to_vec_named(rows)``. The
    existing EG client owns the matching MessagePack transport codec.  The
    client helper is used for nested JSON columns; the row envelope is emitted
    with the same MessagePack implementation so the Rust DTO's one typed f32
    score can retain its declared width. Rust's ``BTreeMap`` rows are
    normalized to sorted mapping keys before that codec is called.
    """
    try:
        from epistemic_graph.client import _pack_binary_msgpack

        msgpack = cast(Any, importlib.import_module("msgpack"))
        # ``msgpack.Packer(use_single_float=True)`` is used only for the
        # typed ``ForeignReadRow.score`` field.  The other row fields, in
        # particular JSON column values, must retain the ordinary EG client
        # codec's f64 behaviour.  The map/sequence headers and scalar values
        # still come from that same MessagePack implementation; this only
        # preserves the Rust DTO's declared f32 width at the one typed field.
        normal = msgpack.Packer(use_bin_type=True)
        score = msgpack.Packer(use_bin_type=True, use_single_float=True)
        encoded = bytearray(normal.pack_array_header(len(rows)))
        for row in rows:
            wire = _wire(row)
            columns = dict(sorted(wire["columns"].items()))
            encoded.extend(normal.pack_map_header(4))
            encoded.extend(normal.pack("id"))
            encoded.extend(normal.pack(wire["id"]))
            encoded.extend(normal.pack("score"))
            encoded.extend(
                normal.pack(None)
                if wire["score"] is None
                else score.pack(wire["score"])
            )
            encoded.extend(normal.pack("columns"))
            encoded.extend(_pack_binary_msgpack(columns))
            encoded.extend(normal.pack("provenance"))
            encoded.extend(normal.pack(wire["provenance"]))
        return len(encoded)
    except Exception:
        raise ValueError("foreign-read MessagePack codec unavailable") from None


def _abort_reason(error: ForeignReadError) -> str:
    """Map a closed client failure to a bounded server abort reason."""
    if error.reason == "deadline":
        return "deadline"
    if error.reason == "expired":
        return "expired"
    return "source_failed"


def _execution_matches(expected: ForeignReadExecutionRef, actual: Any) -> bool:
    return bool(actual == expected)


class ForeignReadClient:
    """Bounded generic receiver over an authenticated request/response adapter."""

    def __init__(self, transport: RequestResponseAdapter) -> None:
        self._transport = transport
        self._executions: dict[int, _Execution] = {}
        self._tombstones: OrderedDict[int, ForeignReadExecutionRef] = OrderedDict()
        self._admission_lock = asyncio.Lock()
        self._pending_opens = 0

    async def open(self, request: OpenRequest) -> OpenResult:
        """Open one approved source execution and record its server handle."""
        if request.schema_version != FOREIGN_READ_SCHEMA_VERSION:
            raise ForeignReadError("schema_mismatch", "open")
        async with self._admission_lock:
            self._reap_expired()
            if len(self._executions) + self._pending_opens >= _MAX_EXECUTIONS:
                raise ForeignReadError("limit_exceeded", "open")
            self._pending_opens += 1
        reserved = True
        started = time.monotonic()
        validated_result: OpenResult | None = None
        try:
            result = await self._call(
                "ForeignReadOpen",
                request,
                timeout=request.limits.deadline_ms / 1000,
            )
            if result.schema_version != FOREIGN_READ_SCHEMA_VERSION:
                raise ForeignReadError("schema_mismatch", "open")
            if result.execution.query_digest != request.query_digest:
                raise ForeignReadError("digest", "open")
            if result.next_sequence != 0:
                raise ForeignReadError("sequence", "open")
            deadline_at = started + request.limits.deadline_ms / 1000
            if result.expires_at_ms <= int(time.time() * 1000):
                raise ForeignReadError("expired", "open")
            # From this point the server-issued handle is trustworthy enough to
            # close if the caller is cancelled while the admission fence is
            # being installed.  A cancellation before this point has no opaque
            # handle to abort.
            validated_result = cast(ForeignReadOpenResult, result)
            execution = _Execution(
                request=request,
                opened=result,
                deadline_at=deadline_at,
                expected_sequence=result.next_sequence,
                lock=asyncio.Lock(),
            )
            async with self._admission_lock:
                self._pending_opens -= 1
                reserved = False
                if (
                    result.execution.execution_id in self._executions
                    or result.execution.execution_id in self._tombstones
                ):
                    raise ForeignReadError("invalid_response", "open")
                self._executions[result.execution.execution_id] = execution
            return cast(ForeignReadOpenResult, result)
        except asyncio.CancelledError:
            if validated_result is not None:
                await self._abort_untracked(
                    validated_result.execution,
                    validated_result.next_sequence,
                    reason="cancelled",
                )
            raise
        except ForeignReadError:
            if validated_result is not None:
                await self._abort_untracked(
                    validated_result.execution,
                    validated_result.next_sequence,
                    reason="source_failed",
                )
            raise
        finally:
            if reserved:
                async with self._admission_lock:
                    self._pending_opens -= 1

    async def chunk(self, request: ChunkRequest) -> ChunkResult:
        """Append one bounded page, enforcing the local monotone sequence."""
        execution = self._find(request.execution)
        async with execution.lock:
            self._check_open(execution, request.execution, "chunk")
            if request.sequence != execution.expected_sequence:
                raise ForeignReadError("sequence", "chunk")
            if request.source_identity != execution.opened.source_identity:
                raise ForeignReadError("digest", "chunk")
            if len(request.rows) > execution.request.limits.chunk_rows:
                raise ForeignReadError("limit_exceeded", "chunk")
            try:
                encoded_rows = _encoded_rows_bytes(request.rows)
            except ValueError:
                raise ForeignReadError("invalid_request", "chunk") from None
            if encoded_rows > execution.request.limits.chunk_bytes:
                raise ForeignReadError("limit_exceeded", "chunk")
            if (
                execution.total_rows + len(request.rows)
                > execution.request.limits.max_rows
                or execution.total_bytes + encoded_rows
                > execution.request.limits.max_bytes
            ):
                raise ForeignReadError("limit_exceeded", "chunk")
            try:
                result = await self._call(
                    "ForeignReadChunk",
                    request,
                    timeout=self._remaining(execution, "chunk"),
                )
            except asyncio.CancelledError:
                await self._abort_execution(execution, reason="cancelled")
                self._terminalize(execution)
                raise
            except ForeignReadError as exc:
                await self._abort_execution(execution, reason=_abort_reason(exc))
                self._terminalize(execution)
                raise
            try:
                if not _execution_matches(request.execution, result.execution):
                    raise ForeignReadError("digest", "chunk")
                if result.sequence != request.sequence:
                    raise ForeignReadError("sequence", "chunk")
                if result.accepted_rows != len(request.rows):
                    raise ForeignReadError("invalid_response", "chunk")
                self._check_totals(
                    execution,
                    result.total_rows,
                    result.total_bytes,
                    len(request.rows),
                    "chunk",
                )
                if result.next_sequence != request.sequence + 1:
                    raise ForeignReadError("sequence", "chunk")
            except ForeignReadError as exc:
                # A response mismatch makes the server handle unsafe to reuse;
                # never retry a phase after accepting a malformed response.
                await self._abort_execution(execution, reason=_abort_reason(exc))
                self._terminalize(execution)
                raise
            execution.expected_sequence = result.next_sequence
            execution.total_rows = result.total_rows
            execution.total_bytes = result.total_bytes
            return cast(ForeignReadChunkResult, result)

    async def complete(self, request: CompleteRequest) -> CompleteResult:
        """Close one open execution successfully, exactly once."""
        execution = self._find(request.execution)
        async with execution.lock:
            self._check_open(execution, request.execution, "complete")
            if request.sequence != execution.expected_sequence:
                raise ForeignReadError("sequence", "complete")
            try:
                result = await self._call(
                    "ForeignReadComplete",
                    request,
                    timeout=self._remaining(execution, "complete"),
                )
                self._check_terminal_result(
                    execution,
                    result.execution,
                    result.sequence,
                    request.sequence,
                    "complete",
                )
                if (result.total_rows, result.total_bytes) != (
                    execution.total_rows,
                    execution.total_bytes,
                ):
                    raise ForeignReadError("invalid_response", "complete")
            except asyncio.CancelledError:
                await self._abort_execution(execution, reason="cancelled")
                self._terminalize(execution)
                raise
            except ForeignReadError as exc:
                await self._abort_execution(execution, reason=_abort_reason(exc))
                self._terminalize(execution)
                raise
            self._terminalize(execution)
            return cast(ForeignReadCompleteResult, result)

    async def abort(self, request: AbortRequest) -> AbortResult:
        """Close one open execution as failed/cancelled, exactly once."""
        execution = self._find(request.execution)
        async with execution.lock:
            self._check_open(execution, request.execution, "abort")
            if request.sequence != execution.expected_sequence:
                raise ForeignReadError("sequence", "abort")
            try:
                result = await self._call(
                    "ForeignReadAbort",
                    request,
                    timeout=self._remaining(execution, "abort"),
                )
                self._check_terminal_result(
                    execution,
                    result.execution,
                    result.sequence,
                    request.sequence,
                    "abort",
                )
                if result.reason != request.reason:
                    raise ForeignReadError("invalid_response", "abort")
            except asyncio.CancelledError:
                self._terminalize(execution)
                raise
            except ForeignReadError:
                self._terminalize(execution)
                raise
            self._terminalize(execution)
            return cast(ForeignReadAbortResult, result)

    async def cancel(self, execution: ForeignReadExecutionRef) -> AbortResult:
        """Use the canonical abort phase for an explicit cancellation."""
        state = self._find(execution)
        return await self.abort(
            AbortRequest(
                execution=execution,
                sequence=state.expected_sequence,
                reason="cancelled",
            )
        )

    async def _call(
        self, method: ForeignReadMethod, request: BaseModel, *, timeout: float
    ) -> Any:
        if timeout <= 0:
            raise ForeignReadError("deadline", method)
        failure: str | None = None
        try:
            async with asyncio.timeout(timeout):
                raw = await self._transport.request(method, {"request": _wire(request)})
        except ForeignReadError as exc:
            failure = exc.reason
        except TimeoutError:
            failure = "deadline"
        except asyncio.CancelledError:
            raise
        except Exception:
            failure = "transport"
        if failure is not None:
            raise ForeignReadError(failure, method)

        response_failure: str | None = None
        try:
            return self._model_for(method, _payload(raw))
        except ForeignReadError as exc:
            response_failure = exc.reason
        except Exception:
            response_failure = "invalid_response"
        if response_failure is not None:
            raise ForeignReadError(response_failure, method)
        raise AssertionError("foreign-read response handling did not return")

    async def _abort_untracked(
        self,
        execution: ForeignReadExecutionRef,
        sequence: int,
        *,
        reason: str,
    ) -> None:
        """Best-effort abort for a validated handle not yet in ``_executions``."""
        request = ForeignReadAbortRequest(
            execution=execution,
            sequence=sequence,
            reason=reason,
        )
        await self._abort_request(request)

    async def _abort_execution(self, state: _Execution, *, reason: str) -> None:
        """Close a server handle after a failed in-flight phase.

        The phase lock is held by the caller, so this deliberately sends the
        abort through the transport rather than calling ``abort`` recursively.
        Cleanup is bounded and never replaces the original phase failure.
        """
        if state.terminal:
            return
        await self._abort_untracked(
            state.opened.execution,
            state.expected_sequence,
            reason=reason,
        )

    async def _abort_request(self, request: AbortRequest) -> None:
        """Issue one bounded abort without leaking a task on cancellation."""
        task = asyncio.create_task(
            self._call(
                "ForeignReadAbort",
                request,
                timeout=_ABORT_CLEANUP_TIMEOUT_S,
            )
        )
        try:
            async with asyncio.timeout(_ABORT_CLEANUP_TIMEOUT_S):
                result = await asyncio.shield(task)
            self._check_abort_result(request, result)
        except BaseException:
            # The caller's cancellation or the abort transport failure must not
            # mask the phase error.  Do cancel and join the shielded task so a
            # late transport response cannot outlive the client operation.
            if not task.done():
                task.cancel()
            with contextlib.suppress(BaseException):
                await task

    @staticmethod
    def _check_abort_result(request: AbortRequest, result: Any) -> None:
        if not _execution_matches(request.execution, result.execution):
            raise ForeignReadError("digest", "abort")
        if result.sequence != request.sequence:
            raise ForeignReadError("sequence", "abort")
        if result.reason != request.reason:
            raise ForeignReadError("invalid_response", "abort")

    @staticmethod
    def _model_for(method: ForeignReadMethod, value: Any) -> Any:
        models: dict[ForeignReadMethod, type[BaseModel]] = {
            "ForeignReadOpen": ForeignReadOpenResult,
            "ForeignReadChunk": ForeignReadChunkResult,
            "ForeignReadComplete": ForeignReadCompleteResult,
            "ForeignReadAbort": ForeignReadAbortResult,
        }
        return models[method].model_validate(value)

    def _find(self, execution: ForeignReadExecutionRef) -> _Execution:
        found = self._executions.get(execution.execution_id)
        if found is None:
            if execution.execution_id in self._tombstones:
                raise ForeignReadError("terminal", "client")
            raise ForeignReadError("unknown_execution", "client")
        return found

    def _terminalize(self, state: _Execution) -> None:
        """Drop request/response payloads while retaining a bounded replay fence."""
        state.terminal = True
        execution_id = state.opened.execution.execution_id
        self._executions.pop(execution_id, None)
        self._tombstones[execution_id] = state.opened.execution
        self._tombstones.move_to_end(execution_id)
        while len(self._tombstones) > _MAX_EXECUTIONS:
            self._tombstones.popitem(last=False)

    def _reap_expired(self) -> None:
        """Reap idle local handles before admitting another execution."""
        now_mono = time.monotonic()
        now_wall_ms = int(time.time() * 1000)
        for state in tuple(self._executions.values()):
            # A phase holding this lock is still resolving an in-flight request;
            # let its own timeout/cancellation path terminalize it.
            if state.lock.locked():
                continue
            if (
                state.deadline_at <= now_mono
                or state.opened.expires_at_ms <= now_wall_ms
            ):
                self._terminalize(state)

    def _check_open(
        self, state: _Execution, execution: ForeignReadExecutionRef, stage: str
    ) -> None:
        if state.terminal:
            raise ForeignReadError("terminal", stage)
        if not _execution_matches(state.opened.execution, execution):
            raise ForeignReadError("digest", stage)
        self._remaining(state, stage)

    def _remaining(self, state: _Execution, stage: str) -> float:
        local = state.deadline_at - time.monotonic()
        server = (state.opened.expires_at_ms - int(time.time() * 1000)) / 1000
        remaining = min(local, server)
        if remaining <= 0:
            self._terminalize(state)
            raise ForeignReadError("expired", stage)
        return remaining

    def _check_totals(
        self,
        state: _Execution,
        total_rows: int,
        total_bytes: int,
        added_rows: int,
        stage: str,
    ) -> None:
        if total_rows != state.total_rows + added_rows:
            raise ForeignReadError("invalid_response", stage)
        if (
            total_bytes < state.total_bytes
            or total_rows > state.request.limits.max_rows
        ):
            raise ForeignReadError("limit_exceeded", stage)
        if total_bytes - state.total_bytes > state.request.limits.chunk_bytes:
            raise ForeignReadError("limit_exceeded", stage)
        if total_bytes > state.request.limits.max_bytes:
            raise ForeignReadError("limit_exceeded", stage)

    @staticmethod
    def _check_terminal_result(
        state: _Execution,
        execution: ForeignReadExecutionRef,
        sequence: int,
        expected_sequence: int,
        stage: str,
    ) -> None:
        if not _execution_matches(state.opened.execution, execution):
            raise ForeignReadError("digest", stage)
        if sequence != expected_sequence:
            raise ForeignReadError("sequence", stage)
