"""ASGI Host, Origin, and trusted-ingress boundaries for MCP servers."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from scion_sdk.mcp._http_reply import _reject
from scion_sdk.mcp.network_validation import (
    normalize_cidrs,
    normalize_host_authorities,
    normalize_host_authority,
    normalize_origin,
    normalize_origins,
)

_MAX_HEADER_VALUE_BYTES = 16_384


def _header_values(scope: Mapping[str, Any], name: bytes) -> list[bytes]:
    target = name.lower()
    return [
        bytes(value)
        for key, value in scope.get("headers", ())
        if bytes(key).lower() == target
    ]


def _normalized_header(
    values: list[bytes], normalizer: Callable[[object], str]
) -> str | None:
    """The normalised value of a single, bounded header; ``None`` otherwise."""
    if len(values) != 1 or len(values[0]) > _MAX_HEADER_VALUE_BYTES:
        return None
    try:
        return normalizer(values[0].decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return None


def _peer_admitted(networks: tuple[Any, ...], scope: Any) -> bool:
    try:
        peer = ipaddress.ip_address(str(scope.get("client")[0]))
    except (IndexError, TypeError, ValueError):
        return False
    return any(peer in network for network in networks)


class _BoundaryMiddleware:
    """Admit non-HTTP scopes and requests ``admits`` accepts; reject the rest."""

    def __init__(
        self, app: Any, admits: Callable[[Any], bool], *, status: int, reason: str
    ) -> None:
        self.app = app
        self._admits = admits
        self._status = status
        self._reason = reason

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") not in {"http", "websocket"} or self._admits(scope):
            await self.app(scope, receive, send)
            return
        await _reject(scope, send, status=self._status, reason=self._reason)


class _ExactHostAuthorityMiddleware(_BoundaryMiddleware):
    def __init__(self, app: Any, allowed_hosts: Iterable[str]) -> None:
        hosts = frozenset(normalize_host_authorities(allowed_hosts))
        super().__init__(
            app,
            lambda scope: (
                _normalized_header(
                    _header_values(scope, b"host"), normalize_host_authority
                )
                in hosts
            ),
            status=400,
            reason="host rejected",
        )


class _OriginPolicyMiddleware(_BoundaryMiddleware):
    def __init__(self, app: Any, allowed_origins: Iterable[str] = ()) -> None:
        origins = frozenset(normalize_origins(allowed_origins))

        def admits(scope: Any) -> bool:
            values = _header_values(scope, b"origin")
            return not values or _normalized_header(values, normalize_origin) in origins

        super().__init__(app, admits, status=403, reason="origin rejected")


class _TrustedProxyPeerMiddleware(_BoundaryMiddleware):
    def __init__(self, app: Any, trusted_cidrs: Iterable[str]) -> None:
        networks = tuple(
            ipaddress.ip_network(value) for value in normalize_cidrs(trusted_cidrs)
        )
        super().__init__(
            app,
            lambda scope: _peer_admitted(networks, scope),
            status=403,
            reason="peer rejected",
        )
