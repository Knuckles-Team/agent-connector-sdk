"""Bounded fallback for host-authorized equivalent platform reads."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import anyio
import anyio.to_process

from scion_sdk.adapters._platform_validation import (
    _platform_request_digest,
    _validate_page,
    _verify_schema,
)
from scion_sdk.adapters.platform_backend import (
    BackendAdmissionRefusal,
    BackendFailure,
    BackendPage,
    PlatformAuthorizer,
    PlatformBackendAdmission,
)
from scion_sdk.adapters.platform_models import (
    BackendAttempt,
    BackendPolicy,
    ChannelStatus,
    PlatformCapability,
    PlatformRequest,
    PlatformResult,
    Reason,
    SkippedBackend,
    validate_request_binding,
)
from scion_sdk.adapters.platform_status import PlatformStatusStore
from scion_sdk.http.retry import RetryPolicy
from scion_sdk.identity import ActorContext


class PlatformStatusError(RuntimeError):
    """Status cannot be read because its authorization authority is unavailable."""


_TRANSIENT = frozenset({"connection_failed", "timeout", "upstream_unavailable"})
_TERMINAL = frozenset(
    {
        "rate_limited",
        "unauthorized",
        "egress_denied",
        "trust_failed",
        "invalid_response",
        "not_found",
    }
)


def _failure_reason(failure: BackendFailure) -> Reason:
    """An observed HTTP refusal cannot be downgraded into a retryable failure."""
    status = failure.http_status
    if status in {401, 403}:
        return "unauthorized"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status is not None and 400 <= status < 500 and status != 408:
        return "invalid_response"
    return (
        failure.reason
        if failure.reason in _TRANSIENT | _TERMINAL
        else "invalid_response"
    )


def _refused(
    request: PlatformRequest,
    reason: str,
    *,
    attempts: Sequence[BackendAttempt] = (),
    skipped: Sequence[SkippedBackend] = (),
    capability: PlatformCapability | None = None,
) -> PlatformResult:
    return PlatformResult.model_validate(
        {
            "request_id": request.request_id,
            "request_digest": _platform_request_digest(request),
            "tenant_id": request.tenant_id,
            "principal_id": request.principal_id,
            "connector_id": request.connector_id,
            "platform_id": request.platform_id,
            "channel_id": request.channel_id,
            "operation": request.operation,
            "policy_revision": capability.policy_revision if capability else None,
            "output_schema_digest": capability.backends[0].output_schema_digest
            if capability
            else None,
            "outcome": "refused",
            "reason": reason,
            "attempts": tuple(attempts),
            "skipped_backends": tuple(skipped),
        }
    )


@dataclass
class _RunState:
    actor: ActorContext
    request: PlatformRequest
    capability: PlatformCapability
    deadline: float
    attempts: list[BackendAttempt]
    skipped: list[SkippedBackend]
    inflight: list[float]


@dataclass(frozen=True)
class _Try:
    index: int
    max_attempts: int
    retry: RetryPolicy


def _elapsed_ms(started: float) -> int:
    return min(30_000, max(0, int((time.monotonic() - started) * 1000)))


async def _schema_verified(backend: Any, policy: BackendPolicy) -> bool:
    try:
        await anyio.to_process.run_sync(
            _verify_schema,
            backend.output_model,
            policy.output_schema_digest,
            cancellable=True,
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return True


async def _read_page(
    backend: Any, request: PlatformRequest, remaining: float
) -> tuple[BackendPage | None, BackendFailure | None]:
    try:
        with anyio.fail_after(remaining):
            page = await backend.read(request, timeout_ms=max(1, int(remaining * 1000)))
    except TimeoutError:
        return None, BackendFailure("timeout")
    except BackendFailure as exc:
        return None, exc
    except Exception:
        return None, BackendFailure("invalid_response")
    return page, None


class PlatformFallback:
    """Use admitted backends in policy order, without introducing authority."""

    def __init__(
        self,
        capabilities: Sequence[PlatformCapability],
        *,
        connector_id: str,
        authorizer: PlatformAuthorizer,
        admission: PlatformBackendAdmission,
        retry_policies: Mapping[str, RetryPolicy],
    ) -> None:
        self._capabilities = {
            (
                c.platform_id,
                c.channel_id,
                c.operation,
            ): PlatformCapability.model_validate(c.model_dump(mode="python"))
            for c in capabilities
        }
        if not connector_id or len(self._capabilities) != len(capabilities):
            raise ValueError("connector identity and unique capabilities are required")
        self._connector = connector_id
        self._authorizer = authorizer
        self._admission = admission
        self._retry_policies = dict(retry_policies)
        if any(
            policy.retry_policy not in self._retry_policies
            for capability in self._capabilities.values()
            for policy in capability.backends
        ):
            raise ValueError("every backend requires a declared retry policy")
        self._status = PlatformStatusStore()

    def _observed_refusal(
        self,
        request: PlatformRequest,
        capability: PlatformCapability,
        reason: str,
        attempts: Sequence[BackendAttempt],
        skipped: Sequence[SkippedBackend],
    ) -> PlatformResult:
        result = _refused(
            request,
            reason,
            attempts=attempts,
            skipped=skipped,
            capability=capability,
        )
        if attempts and reason not in {"unauthorized", "trust_failed"}:
            status = self._status.record(
                request, capability, tuple(attempts), None, tuple(skipped)
            )
            return result.model_copy(update={"channel_status": status})
        return result

    async def status(
        self, actor: ActorContext, request: PlatformRequest
    ) -> ChannelStatus | None:
        """Return authorized, request-scoped observations without probing."""
        request = PlatformRequest.model_validate(request.model_dump(mode="python"))
        capability = self._capabilities.get(
            (request.platform_id, request.channel_id, request.operation)
        )
        if (
            capability is None
            or not actor.authenticated
            or actor.actor_id != request.principal_id
            or actor.tenant_id != request.tenant_id
            or request.connector_id != self._connector
        ):
            return None
        failed = False
        try:
            validate_request_binding(request, capability)
            with anyio.fail_after(request.deadline_ms / 1000):
                if not await self._authorizer.authorize(actor, request, capability):
                    return None
                if request.continuation is not None and not (
                    await self._authorizer.verify_continuation(
                        actor, request, capability
                    )
                ):
                    return None
        except (ValueError, TimeoutError):
            return None
        except Exception:
            failed = True
        if failed:
            raise PlatformStatusError("platform status authority unavailable")
        return self._status.get(request, capability)

    async def execute(
        self, actor: ActorContext, request: PlatformRequest
    ) -> PlatformResult:
        """Authorize and execute a single read or search with one total deadline."""
        request = PlatformRequest.model_validate(request.model_dump(mode="python"))
        capability = self._capabilities.get(
            (request.platform_id, request.channel_id, request.operation)
        )
        if capability is None:
            return _refused(request, "unsupported_capability")
        if (
            not actor.authenticated
            or actor.actor_id != request.principal_id
            or actor.tenant_id != request.tenant_id
            or request.connector_id != self._connector
        ):
            return _refused(request, "unauthorized", capability=capability)
        try:
            validate_request_binding(request, capability)
        except ValueError:
            return _refused(request, "invalid_request", capability=capability)
        deadline = time.monotonic() + request.deadline_ms / 1000
        attempts: list[BackendAttempt] = []
        skipped: list[SkippedBackend] = []
        inflight: list[float] = []
        try:
            with anyio.fail_after(max(0, deadline - time.monotonic())):
                if not await self._authorizer.authorize(actor, request, capability):
                    return _refused(request, "unauthorized", capability=capability)
                if (
                    request.continuation is not None
                    and not await self._authorizer.verify_continuation(
                        actor, request, capability
                    )
                ):
                    return _refused(request, "invalid_request", capability=capability)
                return await self._run(
                    actor, request, capability, deadline, attempts, skipped, inflight
                )
        except TimeoutError:
            if attempts and inflight:
                elapsed = min(
                    30_000, max(0, int((time.monotonic() - inflight[0]) * 1000))
                )
                attempts[-1] = attempts[-1].model_copy(update={"elapsed_ms": elapsed})
            return self._observed_refusal(
                request, capability, "deadline_exceeded", attempts, skipped
            )
        except Exception:
            return _refused(
                request,
                "trust_failed",
                attempts=attempts,
                skipped=skipped,
                capability=capability,
            )

    async def _run(
        self,
        actor: ActorContext,
        request: PlatformRequest,
        capability: PlatformCapability,
        deadline: float,
        attempts: list[BackendAttempt],
        skipped: list[SkippedBackend],
        inflight: list[float],
    ) -> PlatformResult:
        ctx = _RunState(
            actor, request, capability, deadline, attempts, skipped, inflight
        )
        for policy in capability.backends:
            result = await self._run_backend(ctx, policy)
            if result is not None:
                return result
        reason = "chain_exhausted" if attempts else "no_backend"
        return self._observed_refusal(request, capability, reason, attempts, skipped)

    async def _run_backend(
        self, ctx: _RunState, policy: BackendPolicy
    ) -> PlatformResult | None:
        """Try one backend; None means move on to the next policy."""
        continuation = ctx.request.continuation
        if continuation is not None and continuation.backend_id != policy.backend_id:
            return None
        if not policy.enabled:
            ctx.skipped.append(
                SkippedBackend(backend_id=policy.backend_id, reason="disabled")
            )
            return None
        backend = await self._admission.admit(ctx.actor, ctx.request, policy)
        if isinstance(backend, BackendAdmissionRefusal):
            ctx.skipped.append(
                SkippedBackend(backend_id=policy.backend_id, reason=backend.reason)
            )
            return None
        if backend.policy != policy or not await _schema_verified(backend, policy):
            return _refused(
                ctx.request,
                "trust_failed",
                attempts=ctx.attempts,
                skipped=ctx.skipped,
                capability=ctx.capability,
            )
        retry = self._retry_policies[policy.retry_policy]
        max_attempts = min(policy.max_attempts, retry.max_attempts)
        for index in range(1, max_attempts + 1):
            result = await self._attempt(
                ctx, policy, backend, _Try(index, max_attempts, retry)
            )
            if result is not None:
                return result
        return None

    async def _attempt(
        self,
        ctx: _RunState,
        policy: BackendPolicy,
        backend: Any,
        step: _Try,
    ) -> PlatformResult | None:
        """One backend call; None means the caller proceeds to the next attempt."""
        started = time.monotonic()
        wall = int(time.time())
        remaining = min(policy.timeout_ms / 1000, max(0, ctx.deadline - started))
        ctx.inflight[:] = [started]
        ctx.attempts.append(
            BackendAttempt(
                sequence=len(ctx.attempts) + 1,
                backend_id=policy.backend_id,
                attempt_number=step.index,
                outcome="failed",
                reason="timeout",
                started_at=wall,
                elapsed_ms=0,
            )
        )
        page, failure = await _read_page(backend, ctx.request, remaining)
        if failure is None and page is not None:
            outcome = await self._validated(
                ctx, policy, backend, page, (step.index, started, wall, remaining)
            )
            if isinstance(outcome, PlatformResult):
                return outcome
            failure = outcome
        if failure is None:
            failure = BackendFailure("invalid_response")
        if ctx.inflight:
            ctx.attempts.pop()
            ctx.inflight.clear()
        reason = _failure_reason(failure)
        ctx.attempts.append(
            BackendAttempt(
                sequence=len(ctx.attempts) + 1,
                backend_id=policy.backend_id,
                attempt_number=step.index,
                outcome="failed",
                reason=reason,
                started_at=wall,
                elapsed_ms=_elapsed_ms(started),
                http_status=failure.http_status,
                retry_after_ms=failure.retry_after_ms,
            )
        )
        return await self._after_failure(ctx, reason, failure, step)

    async def _validated(
        self,
        ctx: _RunState,
        policy: BackendPolicy,
        backend: Any,
        page: BackendPage,
        timing: tuple[int, float, int, float],
    ) -> PlatformResult | BackendFailure:
        index, started, wall, remaining = timing
        request, capability = ctx.request, ctx.capability
        try:
            validation_remaining = max(0.0, remaining - (time.monotonic() - started))
            with anyio.fail_after(validation_remaining):
                (
                    validated_page,
                    canonical_page,
                ) = await anyio.to_process.run_sync(
                    _validate_page,
                    page,
                    request,
                    capability,
                    backend.output_model,
                    cancellable=True,
                )
            elapsed = _elapsed_ms(started)
            ctx.attempts.pop()
            ctx.inflight.clear()
            attempt = BackendAttempt(
                sequence=len(ctx.attempts) + 1,
                backend_id=policy.backend_id,
                attempt_number=index,
                outcome="ok",
                started_at=wall,
                elapsed_ms=elapsed,
                response_digest="sha256:" + hashlib.sha256(canonical_page).hexdigest(),
            )
            result = PlatformResult(
                request_id=request.request_id,
                request_digest=_platform_request_digest(request),
                tenant_id=request.tenant_id,
                principal_id=request.principal_id,
                connector_id=request.connector_id,
                platform_id=request.platform_id,
                channel_id=request.channel_id,
                operation=request.operation,
                policy_revision=capability.policy_revision,
                output_schema_digest=policy.output_schema_digest,
                outcome="ok",
                selected_backend=policy.backend_id,
                records=validated_page.records,
                continuation=validated_page.continuation,
                provenance=validated_page.provenance,
                attempts=(*ctx.attempts, attempt),
                skipped_backends=tuple(ctx.skipped),
            )
        except TimeoutError:
            return BackendFailure("timeout")
        except (TypeError, ValueError):
            return BackendFailure("invalid_response")
        status = self._status.record(
            request,
            capability,
            result.attempts,
            policy.backend_id,
            result.skipped_backends,
        )
        return result.model_copy(update={"channel_status": status})

    async def _after_failure(
        self,
        ctx: _RunState,
        reason: str,
        failure: BackendFailure,
        step: _Try,
    ) -> PlatformResult | None:
        """Decide retry, sleep or refusal after a failed attempt."""
        request, capability = ctx.request, ctx.capability

        def refuse(why: str) -> PlatformResult:
            return self._observed_refusal(
                request, capability, why, ctx.attempts, ctx.skipped
            )

        more = step.index < step.max_attempts
        if reason == "rate_limited" and more and failure.retry_after_ms is not None:
            delay = failure.retry_after_ms / 1000
            if time.monotonic() + delay >= ctx.deadline:
                return refuse("rate_limited")
            await anyio.sleep(delay)
            return None
        if reason not in _TRANSIENT:
            return refuse(reason)
        if more:
            delay = step.retry.backoff(step.index)
            if time.monotonic() + delay >= ctx.deadline:
                return refuse("deadline_exceeded")
            await anyio.sleep(delay)
        return None
