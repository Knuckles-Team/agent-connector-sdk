"""The SSRF policy a governed client's egress is checked against.

This is the typed policy check :func:`check_egress_destination` and the
pinned-address transport :func:`pinned_egress_transport` that
:mod:`scion_sdk.http.client` wires into ``create_http_client``
(SCION-CONNECTOR-CONTROL-R028.2); both are usable on their own by any call site
that must decide whether a destination is a permitted egress target, or must
hold a connection to an already-resolved, already-approved address.
"""

from __future__ import annotations

import ipaddress
import threading
from collections.abc import Collection
from typing import Any

import anyio
import httpx

from scion_sdk.http.egress_address_pin import (
    PinnedAddressTransport,
    pinned_egress_transport,
)
from scion_sdk.http.egress_policy import (
    EgressOptions,
    EgressPolicyError,
    PinnedEgressViolation,
    check_egress_destination,
    normalize_private_hosts,
)
from scion_sdk.http.egress_resolution import (
    _candidate_ips,
    _checked_logical_target,
    _require_pinned_peer,
)
from scion_sdk.http.egress_validation import (
    EgressDecision,
    egress_ip_is_blocked,
    validate_base_url,
    validate_base_url_resolved,
)

__all__ = [
    "AsyncDnsPinnedEgressTransport",
    "DnsPinnedEgressTransport",
    "EgressDecision",
    "EgressOptions",
    "EgressPolicyError",
    "PinnedAddressTransport",
    "PinnedEgressViolation",
    "check_egress_destination",
    "egress_ip_is_blocked",
    "normalize_private_hosts",
    "pinned_egress_transport",
    "validate_base_url",
    "validate_base_url_resolved",
]


def _resolve_pinned_request(
    request: httpx.Request,
    *,
    allowed_private_hosts: frozenset[str],
    allow_loopback: bool,
) -> tuple[str, str, tuple[str, int]]:
    """Resolve one request once and rewrite it to the chosen IP, keeping Host/SNI."""
    logical_url = request.url
    scheme, host = _checked_logical_target(logical_url)
    ips = _candidate_ips(
        logical_url,
        host,
        allowed_private_hosts=allowed_private_hosts,
        allow_loopback=allow_loopback,
    )
    pinned_ip = ips[0]
    address = ipaddress.ip_address(pinned_ip)
    if scheme == "http" and not (address.is_loopback or host in allowed_private_hosts):
        raise PinnedEgressViolation("unencrypted public egress is not permitted")

    request.headers["Host"] = logical_url.netloc.decode("ascii")
    request.url = logical_url.copy_with(host=pinned_ip)
    if scheme == "https":
        request.extensions = {**request.extensions, "sni_hostname": host}
    return (
        host,
        pinned_ip,
        (scheme, logical_url.port or (443 if scheme == "https" else 80)),
    )


class _PinState:
    """Shared per-transport pin bookkeeping for the sync and async transports."""

    def __init__(
        self,
        *,
        policy: EgressOptions,
        verify_peer: bool,
    ) -> None:
        self.allowed_private_hosts = normalize_private_hosts(
            policy.allowed_private_hosts
        )
        self.allow_loopback = policy.allow_loopback
        self.verify_peer = verify_peer
        self._origin_hosts: dict[tuple[str, int], str] = {}
        self._lock = threading.Lock()

    def resolve(self, request: httpx.Request) -> tuple[str, str, tuple[str, int]]:
        return _resolve_pinned_request(
            request,
            allowed_private_hosts=self.allowed_private_hosts,
            allow_loopback=self.allow_loopback,
        )

    def pin(self, request: httpx.Request) -> str:
        return self.bind(self.resolve(request))

    def bind(self, resolved: tuple[str, str, tuple[str, int]]) -> str:
        host, pinned_ip, origin = resolved
        key = (f"{origin[0]}:{pinned_ip}", origin[1])
        with self._lock:
            prior = self._origin_hosts.setdefault(key, host)
        if prior != host:
            raise PinnedEgressViolation("outbound connection reuse crossed origins")
        return pinned_ip


class _PinnedTransportBase:
    """Shared construction for the sync and async DNS-pinned transports."""

    def __init__(
        self,
        inner: Any,
        *,
        allowed_private_hosts: Collection[str] = (),
        allow_loopback: bool = False,
        verify_peer: bool = True,
    ) -> None:
        self._inner = inner
        self._state = _PinState(
            policy=EgressOptions(
                allowed_private_hosts=allowed_private_hosts,
                allow_loopback=allow_loopback,
            ),
            verify_peer=verify_peer,
        )


class DnsPinnedEgressTransport(_PinnedTransportBase, httpx.BaseTransport):
    """Resolves each request once, validates it, and dials only that address.

    Public destinations must resolve to public addresses. A host named in
    ``allowed_private_hosts`` must resolve into loopback, RFC 1918, RFC 6598 or
    IPv6 ULA space. The original name stays in ``Host`` and TLS SNI. Unless
    ``verify_peer`` is off, the connected peer must equal the pinned address.
    """

    _inner: httpx.BaseTransport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        pinned_ip = self._state.pin(request)
        response = self._inner.handle_request(request)
        if self._state.verify_peer:
            try:
                _require_pinned_peer(response, pinned_ip)
            except Exception:
                response.close()
                raise
        return response

    def close(self) -> None:
        self._inner.close()


class AsyncDnsPinnedEgressTransport(_PinnedTransportBase, httpx.AsyncBaseTransport):
    """The asynchronous :class:`DnsPinnedEgressTransport`."""

    _inner: httpx.AsyncBaseTransport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        probe = httpx.Request(
            request.method,
            request.url,
            headers=request.headers,
            extensions=request.extensions.copy(),
        )
        resolved = await anyio.to_thread.run_sync(
            self._state.resolve, probe, abandon_on_cancel=True
        )
        pinned_ip = self._state.bind(resolved)
        request.url = probe.url
        request.headers["Host"] = probe.headers["Host"]
        request.extensions = probe.extensions
        response = await self._inner.handle_async_request(request)
        if self._state.verify_peer:
            try:
                _require_pinned_peer(response, pinned_ip)
            except Exception:
                await response.aclose()
                raise
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()
