"""Transports that send every request to its DNS pin and check the peer.

Each request is pinned by :func:`~agent_connector_sdk.http.egress_policy.pin_request`.
A pooled connection to one address never serves a second logical host, and with
``verify_peer`` the response must come from the pinned address.
"""

from __future__ import annotations

import ipaddress
import threading

import anyio
import httpx

from agent_connector_sdk.http.egress import Resolver
from agent_connector_sdk.http.egress_policy import (
    EgressPolicy,
    Pin,
    PinnedEgressViolation,
    pin_request,
)

__all__ = ["AsyncPinnedEgressTransport", "PinnedEgressTransport"]


def _check_peer(response: httpx.Response, pin: Pin) -> None:
    stream = response.extensions.get("network_stream")
    get_extra_info = getattr(stream, "get_extra_info", None)
    if not callable(get_extra_info):
        raise PinnedEgressViolation("outbound peer identity is unavailable")
    try:
        server_addr = get_extra_info("server_addr")
        peer = ipaddress.ip_address(str(server_addr[0])).compressed
    except (IndexError, TypeError, ValueError) as exc:
        raise PinnedEgressViolation("outbound peer identity is invalid") from exc
    if peer != pin.address:
        raise PinnedEgressViolation("outbound peer did not match its DNS pin")


class _Pinning:
    """Per-transport pinning state shared by the sync and async transports."""

    def __init__(self, policy: EgressPolicy, resolver: Resolver | None) -> None:
        self.policy = policy
        self._resolver = resolver
        self._origins: dict[tuple[str, str, int], str] = {}
        self._lock = threading.Lock()

    def pin(self, request: httpx.Request) -> Pin:
        pin = pin_request(request, self.policy, self._resolver)
        key = (pin.origin[0], pin.address, pin.origin[1])
        with self._lock:
            owner = self._origins.setdefault(key, pin.host)
        if owner != pin.host:
            raise PinnedEgressViolation("a pinned connection would cross origins")
        return pin


class PinnedEgressTransport(httpx.BaseTransport):
    """Pins each synchronous request before the wrapped transport sends it."""

    def __init__(
        self,
        inner: httpx.BaseTransport,
        policy: EgressPolicy,
        *,
        resolver: Resolver | None = None,
    ) -> None:
        self._inner = inner
        self._pinning = _Pinning(policy, resolver)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Pin, send, and check the peer."""
        pin = self._pinning.pin(request)
        response = self._inner.handle_request(request)
        if self._pinning.policy.verify_peer:
            try:
                _check_peer(response, pin)
            except PinnedEgressViolation:
                response.close()
                raise
        return response

    def close(self) -> None:
        """Close the wrapped transport."""
        self._inner.close()


class AsyncPinnedEgressTransport(httpx.AsyncBaseTransport):
    """Pins each asynchronous request before the wrapped transport sends it.

    Resolution runs in a worker thread so it never blocks the event loop.
    """

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        policy: EgressPolicy,
        *,
        resolver: Resolver | None = None,
    ) -> None:
        self._inner = inner
        self._pinning = _Pinning(policy, resolver)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Pin, send, and check the peer."""
        pin = await anyio.to_thread.run_sync(self._pinning.pin, request)
        response = await self._inner.handle_async_request(request)
        if self._pinning.policy.verify_peer:
            try:
                _check_peer(response, pin)
            except PinnedEgressViolation:
                await response.aclose()
                raise
        return response

    async def aclose(self) -> None:
        """Close the wrapped transport."""
        await self._inner.aclose()
