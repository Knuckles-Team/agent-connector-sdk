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
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import BaseModel

from scion_sdk.adapters._foreign_read_codec import _encoded_rows_bytes
from scion_sdk.adapters._foreign_read_models import (
    FOREIGN_READ_SCHEMA_VERSION,
    ForeignReadAbortRequest,
    ForeignReadAbortResult,
    ForeignReadChunkRequest,
    ForeignReadChunkResult,
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
)

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

_MAX_EXECUTIONS = 1024
_ABORT_CLEANUP_TIMEOUT_S = 1.0

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
class _OpenState:
    reserved: bool = True
    validated: OpenResult | None = None


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


def _check_open_result(request: OpenRequest, result: Any) -> None:
    if result.schema_version != FOREIGN_READ_SCHEMA_VERSION:
        raise ForeignReadError("schema_mismatch", "open")
    if result.execution.query_digest != request.query_digest:
        raise ForeignReadError("digest", "open")
    if result.next_sequence != 0:
        raise ForeignReadError("sequence", "open")
    if result.expires_at_ms <= int(time.time() * 1000):
        raise ForeignReadError("expired", "open")


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
        state = _OpenState()
        try:
            return await self._open_reserved(request, state)
        except (asyncio.CancelledError, ForeignReadError) as exc:
            await self._abort_opened(state, exc)
            raise
        finally:
            await self._release_reservation(state)

    async def _release_reservation(self, state: _OpenState) -> None:
        if state.reserved:
            async with self._admission_lock:
                self._pending_opens -= 1

    async def _abort_opened(self, state: _OpenState, exc: BaseException) -> None:
        if state.validated is None:
            return
        reason = (
            "cancelled" if isinstance(exc, asyncio.CancelledError) else "source_failed"
        )
        await self._abort_untracked(
            state.validated.execution, state.validated.next_sequence, reason=reason
        )

    async def _open_reserved(
        self, request: OpenRequest, state: _OpenState
    ) -> OpenResult:
        started = time.monotonic()
        result = await self._call(
            "ForeignReadOpen",
            request,
            timeout=request.limits.deadline_ms / 1000,
        )
        _check_open_result(request, result)
        # From this point the server-issued handle is trustworthy enough to
        # close if the caller is cancelled while the admission fence is
        # being installed.  A cancellation before this point has no opaque
        # handle to abort.
        state.validated = cast(ForeignReadOpenResult, result)
        execution = _Execution(
            request=request,
            opened=result,
            deadline_at=started + request.limits.deadline_ms / 1000,
            expected_sequence=result.next_sequence,
            lock=asyncio.Lock(),
        )
        async with self._admission_lock:
            self._pending_opens -= 1
            state.reserved = False
            self._install(result.execution.execution_id, execution)
        return cast(ForeignReadOpenResult, result)

    def _install(self, execution_id: int, execution: _Execution) -> None:
        if execution_id in self._executions or execution_id in self._tombstones:
            raise ForeignReadError("invalid_response", "open")
        self._executions[execution_id] = execution

    async def _failing_call(
        self,
        execution: _Execution,
        method: ForeignReadMethod,
        request: BaseModel,
        phase: str,
        check: Callable[[Any], None],
    ) -> Any:
        """Call a phase; abort and terminalize the handle on any failure."""
        try:
            return await self._checked_call(execution, method, request, phase, check)
        except asyncio.CancelledError:
            await self._abort_execution(execution, reason="cancelled")
            self._terminalize(execution)
            raise
        except ForeignReadError as exc:
            await self._abort_execution(execution, reason=_abort_reason(exc))
            self._terminalize(execution)
            raise

    async def chunk(self, request: ChunkRequest) -> ChunkResult:
        """Append one bounded page, enforcing the local monotone sequence."""
        execution = self._find(request.execution)
        async with execution.lock:
            self._check_open(execution, request.execution, "chunk")
            if request.sequence != execution.expected_sequence:
                raise ForeignReadError("sequence", "chunk")
            if request.source_identity != execution.opened.source_identity:
                raise ForeignReadError("digest", "chunk")
            self._preflight_chunk(execution, request)
            result = await self._failing_call(
                execution,
                "ForeignReadChunk",
                request,
                "chunk",
                lambda res: self._check_chunk_result(execution, request, res),
            )
            execution.expected_sequence = result.next_sequence
            execution.total_rows = result.total_rows
            execution.total_bytes = result.total_bytes
            return cast(ForeignReadChunkResult, result)

    @staticmethod
    def _preflight_chunk(execution: _Execution, request: ChunkRequest) -> None:
        limits = execution.request.limits
        if len(request.rows) > limits.chunk_rows:
            raise ForeignReadError("limit_exceeded", "chunk")
        try:
            encoded_rows = _encoded_rows_bytes(request.rows)
        except ValueError:
            raise ForeignReadError("invalid_request", "chunk") from None
        if encoded_rows > limits.chunk_bytes:
            raise ForeignReadError("limit_exceeded", "chunk")
        if (
            execution.total_rows + len(request.rows) > limits.max_rows
            or execution.total_bytes + encoded_rows > limits.max_bytes
        ):
            raise ForeignReadError("limit_exceeded", "chunk")

    def _check_chunk_result(
        self, execution: _Execution, request: ChunkRequest, result: Any
    ) -> None:
        # A response mismatch makes the server handle unsafe to reuse; the
        # caller aborts it and never retries a phase after a malformed response.
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

    async def complete(self, request: CompleteRequest) -> CompleteResult:
        """Close one open execution successfully, exactly once."""
        execution = self._find(request.execution)
        async with execution.lock:
            self._check_open(execution, request.execution, "complete")
            if request.sequence != execution.expected_sequence:
                raise ForeignReadError("sequence", "complete")
            result = await self._failing_call(
                execution,
                "ForeignReadComplete",
                request,
                "complete",
                lambda res: self._check_complete_result(execution, request, res),
            )
            self._terminalize(execution)
            return cast(ForeignReadCompleteResult, result)

    def _check_complete_result(
        self, execution: _Execution, request: CompleteRequest, result: Any
    ) -> None:
        self._check_terminal_result(
            execution, result.execution, result.sequence, request.sequence, "complete"
        )
        if (result.total_rows, result.total_bytes) != (
            execution.total_rows,
            execution.total_bytes,
        ):
            raise ForeignReadError("invalid_response", "complete")

    def _check_abort_phase(
        self, execution: _Execution, request: AbortRequest, result: Any
    ) -> None:
        self._check_terminal_result(
            execution, result.execution, result.sequence, request.sequence, "abort"
        )
        if result.reason != request.reason:
            raise ForeignReadError("invalid_response", "abort")

    async def _checked_call(
        self,
        execution: _Execution,
        method: ForeignReadMethod,
        request: BaseModel,
        phase: str,
        check: Callable[[Any], None],
    ) -> Any:
        result = await self._call(
            method, request, timeout=self._remaining(execution, phase)
        )
        check(result)
        return result

    async def abort(self, request: AbortRequest) -> AbortResult:
        """Close one open execution as failed/cancelled, exactly once."""
        execution = self._find(request.execution)
        async with execution.lock:
            self._check_open(execution, request.execution, "abort")
            if request.sequence != execution.expected_sequence:
                raise ForeignReadError("sequence", "abort")
            try:
                result = await self._checked_call(
                    execution,
                    "ForeignReadAbort",
                    request,
                    "abort",
                    lambda res: self._check_abort_phase(execution, request, res),
                )
            except (asyncio.CancelledError, ForeignReadError):
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
