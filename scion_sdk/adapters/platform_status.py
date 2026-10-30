"""Bounded request-authority-scoped observations for platform fallback."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from scion_sdk.adapters.platform_models import (
    BackendAttempt,
    BackendState,
    ChannelStatus,
    PlatformCapability,
    PlatformRequest,
    SkippedBackend,
)

DEFAULT_STATUS_TTL_SECONDS = 60
DEFAULT_STATUS_ENTRIES = 256


@dataclass(frozen=True)
class _StatusKey:
    tenant: str
    principal: str
    connector: str
    platform: str
    channel: str
    operation: str
    policy_revision: str
    account_scope: str


def _key(request: PlatformRequest, capability: PlatformCapability) -> _StatusKey:
    return _StatusKey(
        request.tenant_id,
        request.principal_id,
        request.connector_id,
        request.platform_id,
        request.channel_id,
        request.operation,
        capability.policy_revision,
        capability.backends[0].equivalence_contract.account_scope,
    )


class PlatformStatusStore:
    """Small expiring observation cache; status never confers authority."""

    def __init__(self) -> None:
        self._entries: OrderedDict[_StatusKey, tuple[ChannelStatus, float]] = (
            OrderedDict()
        )
        self._lock = threading.Lock()

    def record(
        self,
        request: PlatformRequest,
        capability: PlatformCapability,
        attempts: tuple[BackendAttempt, ...],
        selected: str | None,
        skipped: tuple[SkippedBackend, ...] = (),
    ) -> ChannelStatus:
        if not attempts or tuple(attempt.sequence for attempt in attempts) != tuple(
            range(1, len(attempts) + 1)
        ):
            raise ValueError("status requires ordered observed attempts")
        if any(
            attempt.backend_id
            not in {policy.backend_id for policy in capability.backends}
            for attempt in attempts
        ):
            raise ValueError("status attempt does not match capability")
        if selected is not None and (
            attempts[-1].outcome != "ok" or attempts[-1].backend_id != selected
        ):
            raise ValueError("status selection must match successful observation")
        if selected is None and any(attempt.outcome == "ok" for attempt in attempts):
            raise ValueError("unavailable status cannot contain a success")
        now = int(time.time())
        states = []
        for policy in capability.backends:
            latest = next(
                (a for a in reversed(attempts) if a.backend_id == policy.backend_id),
                None,
            )
            skipped_reason = next(
                (
                    item.reason
                    for item in skipped
                    if item.backend_id == policy.backend_id
                ),
                None,
            )
            states.append(
                BackendState(
                    backend_id=policy.backend_id,
                    health=(
                        "disabled"
                        if not policy.enabled
                        else "unconfigured"
                        if skipped_reason == "unconfigured"
                        else "untested"
                    )
                    if latest is None
                    else ("healthy" if latest.outcome == "ok" else "failed"),
                    reason=latest.reason if latest is not None else None,
                    observed_at=latest.started_at if latest is not None else None,
                )
            )
        health: Literal["healthy", "degraded", "unavailable"] = (
            "unavailable"
            if selected is None
            else (
                "healthy"
                if selected == capability.backends[0].backend_id
                else "degraded"
            )
        )
        status = ChannelStatus(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            account_scope=capability.backends[0].equivalence_contract.account_scope,
            platform_id=request.platform_id,
            channel_id=request.channel_id,
            operation=request.operation,
            policy_revision=capability.policy_revision,
            selected_backend=selected,
            health=health,
            backend_states=tuple(states),
            observed_at=now,
            expires_at=now + DEFAULT_STATUS_TTL_SECONDS,
        )
        with self._lock:
            key = _key(request, capability)
            self._entries[key] = (status, time.monotonic() + DEFAULT_STATUS_TTL_SECONDS)
            self._entries.move_to_end(key)
            while len(self._entries) > DEFAULT_STATUS_ENTRIES:
                self._entries.popitem(last=False)
        return status

    def get(
        self, request: PlatformRequest, capability: PlatformCapability
    ) -> ChannelStatus:
        """Return a scoped observation; absent and expired state is unknown."""
        with self._lock:
            key = _key(request, capability)
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
        if entry is None:
            return ChannelStatus(
                tenant_id=request.tenant_id,
                connector_id=request.connector_id,
                account_scope=capability.backends[0].equivalence_contract.account_scope,
                platform_id=request.platform_id,
                channel_id=request.channel_id,
                operation=request.operation,
                policy_revision=capability.policy_revision,
                selected_backend=None,
                health="unknown",
                backend_states=tuple(
                    BackendState(
                        backend_id=policy.backend_id,
                        health="untested" if policy.enabled else "disabled",
                    )
                    for policy in capability.backends
                ),
                observed_at=0,
                expires_at=0,
            )
        status, expires_monotonic = entry
        if time.monotonic() >= expires_monotonic:
            states = tuple(
                state.model_copy(update={"health": "untested", "reason": None})
                if state.health in {"healthy", "failed"}
                else state
                for state in status.backend_states
            )
            return status.model_copy(
                update={
                    "health": "unknown",
                    "selected_backend": None,
                    "backend_states": states,
                }
            )
        return status
