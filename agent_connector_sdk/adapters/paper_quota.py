"""Shared, fail-closed provider pacing through EG's durable KV CAS.

The authenticated host supplies a stable credential group and policy revision.
A dead holder requires authorized operator recovery; this module never guesses
lease expiry or creates an authorization decision.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
from epistemic_graph.generated import storage

from agent_connector_sdk.adapters.paper_quota_policy import PaperQuotaPolicy
from agent_connector_sdk.adapters.paper_quota_values import (
    QuotaUnavailable,
    _check_free,
    _encode,
    _key,
)

__all__ = ["PaperQuotaPolicy", "QuotaSlot", "QuotaUnavailable", "SharedPaperQuota"]
_NAMESPACE = "scion-paper-quota"


class QuotaSlot:
    """A held slot that may be retained after an unresolved rate limit."""

    def __init__(self) -> None:
        self._retained = False

    def retain(self) -> None:
        """Fail closed if a provider delay cannot safely finish."""
        self._retained = True

    def release_after_delay(self) -> None:
        """Permit normal release once the provider delay has elapsed."""
        self._retained = False


class SharedPaperQuota:
    """Enforce one shared, exclusive request slot with EG's KV CAS."""

    def __init__(self, client: Any) -> None:
        if client is None:
            raise ValueError("a verified EG client is required")
        self._client = client
        self._kv_lock = anyio.Lock()

    @asynccontextmanager
    async def request_slot(self, policy: PaperQuotaPolicy) -> AsyncIterator[QuotaSlot]:
        """Hold one slot from before spacing until the provider call completes."""
        policy = PaperQuotaPolicy.model_validate(policy.model_dump())
        key = _key(policy)
        owner = uuid.uuid4().hex
        async with self._kv_lock:
            version = await self._acquire(key, owner, policy)
        slot = QuotaSlot()
        try:
            await anyio.sleep(policy.minimum_spacing_ns / 1_000_000_000)
            yield slot
        finally:
            if not slot._retained:
                await self._safe_release(key, owner, policy=policy, version=version)

    async def _safe_release(
        self, key: str, owner: str, *, policy: PaperQuotaPolicy, version: int
    ) -> None:
        with anyio.CancelScope(shield=True):
            async with self._kv_lock:
                await self._release(key, owner, policy, version)

    async def _read(self, key: str) -> Any:
        try:
            return storage.decode_kv_get(
                await storage.send_kv_get(
                    self._client, {"namespace": _NAMESPACE, "key": key, "shared": True}
                )
            )
        except Exception:
            raise QuotaUnavailable("unavailable") from None

    async def _swap(self, key: str, version: int, value: bytes) -> Any:
        try:
            return storage.decode_kv_cas(
                await storage.send_kv_cas(
                    self._client,
                    {
                        "namespace": _NAMESPACE,
                        "key": key,
                        "shared": True,
                        "expected_version": version,
                        "new": value,
                    },
                )
            )
        except Exception:
            raise QuotaUnavailable("unavailable") from None

    async def _acquire(self, key: str, owner: str, policy: PaperQuotaPolicy) -> int:
        entry = await self._read(key)
        version = 0 if entry is None else entry.version
        if entry is not None:
            _check_free(entry.value, policy)
        outcome = await self._swap(key, version, _encode(owner, policy))
        if not outcome.swapped:
            raise QuotaUnavailable("busy")
        return int(outcome.version)

    async def _release(
        self, key: str, owner: str, policy: PaperQuotaPolicy, version: int
    ) -> None:
        entry = await self._read(key)
        if (
            entry is None
            or entry.version != version
            or entry.value != _encode(owner, policy)
        ):
            raise QuotaUnavailable("unavailable")
        outcome = await self._swap(key, version, _encode(None, policy))
        if not outcome.swapped:
            raise QuotaUnavailable("unavailable")
