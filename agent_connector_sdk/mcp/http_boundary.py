"""ASGI Host, Origin, and trusted-ingress boundaries for MCP servers."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from agent_connector_sdk.mcp.network_validation import (
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


async def _json_response(send: Any, status: int, error: str) -> None:
    body = json.dumps({"error": error}, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _normalized_header(value: bytes, normalizer: Callable[[object], str]) -> str | None:
    try:
        return normalizer(value.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return None


class _ExactHostAuthorityMiddleware:
    def __init__(self, app: Any, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self.allowed_hosts = frozenset(normalize_host_authorities(allowed_hosts))

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        values = _header_values(scope, b"host")
        candidate = (
            _normalized_header(values[0], normalize_host_authority)
            if len(values) == 1 and len(values[0]) <= _MAX_HEADER_VALUE_BYTES
            else None
        )
        if candidate in self.allowed_hosts:
            await self.app(scope, receive, send)
            return
        await _reject(scope, send, status=400, reason="host rejected")


class _OriginPolicyMiddleware:
    def __init__(self, app: Any, allowed_origins: Iterable[str] = ()) -> None:
        self.app = app
        self.allowed_origins = frozenset(normalize_origins(allowed_origins))

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        values = _header_values(scope, b"origin")
        if not values:
            await self.app(scope, receive, send)
            return
        candidate = (
            _normalized_header(values[0], normalize_origin)
            if len(values) == 1 and len(values[0]) <= _MAX_HEADER_VALUE_BYTES
            else None
        )
        if candidate in self.allowed_origins:
            await self.app(scope, receive, send)
            return
        await _reject(scope, send, status=403, reason="origin rejected")


class _TrustedProxyPeerMiddleware:
    def __init__(self, app: Any, trusted_cidrs: Iterable[str]) -> None:
        self.app = app
        self.networks = tuple(
            ipaddress.ip_network(value) for value in normalize_cidrs(trusted_cidrs)
        )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        try:
            peer = ipaddress.ip_address(str(client[0]))
        except (IndexError, TypeError, ValueError):
            allowed = False
        else:
            allowed = any(peer in network for network in self.networks)
        if allowed:
            await self.app(scope, receive, send)
            return
        await _reject(scope, send, status=403, reason="peer rejected")


async def _reject(scope: Any, send: Any, *, status: int, reason: str) -> None:
    if scope.get("type") == "websocket":
        await send({"type": "websocket.close", "code": 4403, "reason": reason})
        return
    await _json_response(send, status, reason)
