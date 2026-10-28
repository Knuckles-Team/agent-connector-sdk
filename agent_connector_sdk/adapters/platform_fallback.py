"""Bounded fallback for host-authorized equivalent platform reads."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence

import anyio
import anyio.to_process

from agent_connector_sdk.adapters._platform_validation import (
    _platform_request_digest,
    _validate_page,
    _verify_schema,
)
from agent_connector_sdk.adapters.platform_backend import (
    BackendAdmissionRefusal,
    BackendFailure,
    BackendPage,
    PlatformAuthorizer,
    PlatformBackendAdmission,
)
from agent_connector_sdk.adapters.platform_models import (
    BackendAttempt,
    ChannelStatus,
    PlatformCapability,
    PlatformRequest,
    PlatformResult,
    Reason,
    SkippedBackend,
    validate_request_binding,
)
from agent_connector_sdk.adapters.platform_status import PlatformStatusStore
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.identity import ActorContext


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
        result = _refused(request, reason, attempts, skipped, capability)
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
            return _refused(request, "trust_failed", attempts, skipped, capability)

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
        for policy in capability.backends:
            if (
                request.continuation is not None
                and request.continuation.backend_id != policy.backend_id
            ):
                continue
            if not policy.enabled:
                skipped.append(
                    SkippedBackend(backend_id=policy.backend_id, reason="disabled")
                )
                continue
            backend = await self._admission.admit(actor, request, policy)
            if isinstance(backend, BackendAdmissionRefusal):
                skipped.append(
                    SkippedBackend(backend_id=policy.backend_id, reason=backend.reason)
                )
                continue
            if backend.policy != policy:
                return _refused(request, "trust_failed", attempts, skipped, capability)
            try:
                await anyio.to_process.run_sync(
                    _verify_schema,
                    backend.output_model,
                    policy.output_schema_digest,
                    cancellable=True,
                )
            except (AttributeError, TypeError, ValueError):
                return _refused(request, "trust_failed", attempts, skipped, capability)
            retry = self._retry_policies[policy.retry_policy]
            max_attempts = min(policy.max_attempts, retry.max_attempts)
            for index in range(1, max_attempts + 1):
                started = time.monotonic()
                wall = int(time.time())
                remaining = min(policy.timeout_ms / 1000, max(0, deadline - started))
                page: BackendPage | None = None
                failure: BackendFailure | None = None
                inflight[:] = [started]
                attempts.append(
                    BackendAttempt(
                        sequence=len(attempts) + 1,
                        backend_id=policy.backend_id,
                        attempt_number=index,
                        outcome="failed",
                        reason="timeout",
                        started_at=wall,
                        elapsed_ms=0,
                    )
                )
                try:
                    with anyio.fail_after(remaining):
                        page = await backend.read(
                            request, timeout_ms=max(1, int(remaining * 1000))
                        )
                except TimeoutError:
                    failure = BackendFailure("timeout")
                except BackendFailure as exc:
                    failure = exc
                except Exception:
                    failure = BackendFailure("invalid_response")
                if failure is None and page is not None:
                    try:
                        validation_remaining = max(
                            0.0, remaining - (time.monotonic() - started)
                        )
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
                        elapsed = min(
                            30_000, max(0, int((time.monotonic() - started) * 1000))
                        )
                        attempts.pop()
                        inflight.clear()
                        attempt = BackendAttempt(
                            sequence=len(attempts) + 1,
                            backend_id=policy.backend_id,
                            attempt_number=index,
                            outcome="ok",
                            started_at=wall,
                            elapsed_ms=elapsed,
                            response_digest="sha256:"
                            + hashlib.sha256(canonical_page).hexdigest(),
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
                            attempts=(*attempts, attempt),
                            skipped_backends=tuple(skipped),
                        )
                    except TimeoutError:
                        failure = BackendFailure("timeout")
                    except (TypeError, ValueError):
                        failure = BackendFailure("invalid_response")
                    else:
                        status = self._status.record(
                            request,
                            capability,
                            result.attempts,
                            policy.backend_id,
                            result.skipped_backends,
                        )
                        return result.model_copy(update={"channel_status": status})
                if failure is None:
                    failure = BackendFailure("invalid_response")
                if inflight:
                    attempts.pop()
                    inflight.clear()
                elapsed = min(30_000, max(0, int((time.monotonic() - started) * 1000)))
                reason = _failure_reason(failure)
                attempts.append(
                    BackendAttempt(
                        sequence=len(attempts) + 1,
                        backend_id=policy.backend_id,
                        attempt_number=index,
                        outcome="failed",
                        reason=reason,
                        started_at=wall,
                        elapsed_ms=elapsed,
                        http_status=failure.http_status,
                        retry_after_ms=failure.retry_after_ms,
                    )
                )
                if (
                    reason == "rate_limited"
                    and index < max_attempts
                    and failure.retry_after_ms is not None
                ):
                    delay = failure.retry_after_ms / 1000
                    if time.monotonic() + delay >= deadline:
                        return self._observed_refusal(
                            request, capability, "rate_limited", attempts, skipped
                        )
                    await anyio.sleep(delay)
                    continue
                if reason not in _TRANSIENT:
                    return self._observed_refusal(
                        request, capability, reason, attempts, skipped
                    )
                if index < max_attempts:
                    delay = retry.backoff(index)
                    if time.monotonic() + delay >= deadline:
                        return self._observed_refusal(
                            request, capability, "deadline_exceeded", attempts, skipped
                        )
                    await anyio.sleep(delay)
        reason = "chain_exhausted" if attempts else "no_backend"
        return self._observed_refusal(request, capability, reason, attempts, skipped)
