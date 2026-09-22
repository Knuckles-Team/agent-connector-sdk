"""Typed, fail-closed network-serving contract for MCP applications."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from starlette.middleware import Middleware

from agent_connector_sdk.mcp.auth.policy import AUTH_TYPES
from agent_connector_sdk.mcp.body_boundary import _BoundedRequestBodyMiddleware
from agent_connector_sdk.mcp.exposure import NetworkExposureError, is_loopback_host
from agent_connector_sdk.mcp.http_boundary import (
    _ExactHostAuthorityMiddleware,
    _OriginPolicyMiddleware,
    _TrustedProxyPeerMiddleware,
)
from agent_connector_sdk.mcp.network_inputs import (
    DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    DEFAULT_KEEPALIVE_TIMEOUT_SECONDS,
    DEFAULT_LISTEN_BACKLOG,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_REQUEST_BYTES,
    DEFAULT_REQUEST_BODY_TIMEOUT_SECONDS,
    NETWORK_TRANSPORTS,
    bounded_float,
    bounded_int,
    resolve_network_inputs,
)
from agent_connector_sdk.mcp.network_validation import (
    normalize_cidrs,
    normalize_host_authorities,
    normalize_origins,
)

__all__ = ["NetworkServingConfig", "build_network_serving_config"]

_H11_MAX_INCOMPLETE_EVENT_SIZE = 65_536


@dataclass(frozen=True, slots=True)
class NetworkServingConfig:
    """Validated Starlette and Uvicorn policy for one MCP listener.

    Constructing this value validates the complete serving boundary. Consumers
    pass :meth:`fastmcp_run_kwargs` to ``FastMCP.run``; there is no permissive
    dictionary-only path that can silently omit a boundary.
    """

    transport: Literal["streamable-http", "sse"]
    host: str
    port: int
    auth_type: str
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...] = ()
    tls_certfile: str | None = None
    tls_keyfile: str | None = None
    tls_terminated: bool = False
    trusted_proxy_cidrs: tuple[str, ...] = ()
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    request_body_timeout_seconds: float = DEFAULT_REQUEST_BODY_TIMEOUT_SECONDS
    limit_concurrency: int = DEFAULT_MAX_CONNECTIONS
    backlog: int = DEFAULT_LISTEN_BACKLOG
    timeout_keep_alive: int = DEFAULT_KEEPALIVE_TIMEOUT_SECONDS
    timeout_graceful_shutdown: int = DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        self._validate_listener()
        self._validate_tls()
        self._normalize_boundaries()
        self._validate_resource_bounds()

    def _validate_listener(self) -> None:
        if self.transport not in NETWORK_TRANSPORTS:
            raise NetworkExposureError("network serving requires a network transport")
        if not self.host.strip():
            raise NetworkExposureError("listener host is required")
        object.__setattr__(
            self,
            "port",
            bounded_int(self.port, name="listener port", minimum=0, maximum=65_535),
        )
        if self.auth_type not in AUTH_TYPES:
            raise NetworkExposureError("listener authentication mode is invalid")

    def _validate_tls(self) -> None:
        certfile, keyfile = self._validated_tls_files()
        self._validate_ingress_boundary()
        self._validate_remote_boundary(direct_tls=bool(certfile))
        object.__setattr__(self, "tls_certfile", certfile)
        object.__setattr__(self, "tls_keyfile", keyfile)

    def _validated_tls_files(self) -> tuple[str | None, str | None]:
        certfile = str(self.tls_certfile or "").strip()
        keyfile = str(self.tls_keyfile or "").strip()
        if bool(certfile) != bool(keyfile):
            raise NetworkExposureError("TLS needs both certificate and key")
        if certfile and not (Path(certfile).is_file() and Path(keyfile).is_file()):
            raise NetworkExposureError("TLS certificate or key is unavailable")
        return certfile or None, keyfile or None

    def _validate_ingress_boundary(self) -> None:
        if self.tls_terminated and not self.trusted_proxy_cidrs:
            raise NetworkExposureError(
                "a TLS-terminating ingress needs trusted proxy CIDRs"
            )

    def _validate_remote_boundary(self, *, direct_tls: bool) -> None:
        if is_loopback_host(self.host):
            return
        if self.auth_type == "none":
            raise NetworkExposureError(
                "an exposed MCP listener requires authentication"
            )
        if not direct_tls and not self.tls_terminated:
            raise NetworkExposureError("an exposed MCP listener requires TLS")

    def _normalize_boundaries(self) -> None:
        hosts = self.allowed_hosts
        if not hosts and is_loopback_host(self.host):
            hosts = (
                f"localhost:{self.port}",
                f"127.0.0.1:{self.port}",
                f"[::1]:{self.port}",
                "testserver",
            )
        if not hosts:
            raise NetworkExposureError(
                "an exposed MCP listener requires exact allowed hosts"
            )
        try:
            normalized_hosts = normalize_host_authorities(hosts)
            normalized_origins = normalize_origins(self.allowed_origins)
            normalized_cidrs = (
                normalize_cidrs(self.trusted_proxy_cidrs)
                if self.trusted_proxy_cidrs
                else ()
            )
        except ValueError as exc:
            raise NetworkExposureError(str(exc)) from exc
        object.__setattr__(self, "allowed_hosts", normalized_hosts)
        object.__setattr__(self, "allowed_origins", normalized_origins)
        object.__setattr__(self, "trusted_proxy_cidrs", normalized_cidrs)

    def _validate_resource_bounds(self) -> None:
        checks = (
            ("max_request_bytes", self.max_request_bytes, 1_024, 256 * 1024 * 1024),
            ("limit_concurrency", self.limit_concurrency, 1, 10_000),
            ("backlog", self.backlog, 1, 65_535),
            ("timeout_keep_alive", self.timeout_keep_alive, 1, 300),
            (
                "timeout_graceful_shutdown",
                self.timeout_graceful_shutdown,
                1,
                300,
            ),
        )
        for name, value, minimum, maximum in checks:
            object.__setattr__(
                self,
                name,
                bounded_int(value, name=name, minimum=minimum, maximum=maximum),
            )
        object.__setattr__(
            self,
            "request_body_timeout_seconds",
            bounded_float(
                self.request_body_timeout_seconds,
                name="request_body_timeout_seconds",
                minimum=1.0,
                maximum=300.0,
            ),
        )

    def fastmcp_run_kwargs(self) -> dict[str, Any]:
        """Render the validated FastMCP ``run`` boundary."""
        middleware = [
            Middleware(_ExactHostAuthorityMiddleware, allowed_hosts=self.allowed_hosts),
            Middleware(_OriginPolicyMiddleware, allowed_origins=self.allowed_origins),
            Middleware(
                _BoundedRequestBodyMiddleware,
                max_bytes=self.max_request_bytes,
                read_timeout_seconds=self.request_body_timeout_seconds,
            ),
        ]
        if self.tls_terminated:
            middleware.insert(
                0,
                Middleware(
                    _TrustedProxyPeerMiddleware,
                    trusted_cidrs=self.trusted_proxy_cidrs,
                ),
            )
        uvicorn_config: dict[str, Any] = {
            # The socket peer remains authoritative for the ingress CIDR gate.
            "proxy_headers": False,
            "limit_concurrency": self.limit_concurrency,
            "backlog": self.backlog,
            "timeout_keep_alive": self.timeout_keep_alive,
            "timeout_graceful_shutdown": self.timeout_graceful_shutdown,
            "h11_max_incomplete_event_size": _H11_MAX_INCOMPLETE_EVENT_SIZE,
        }
        if self.tls_certfile and self.tls_keyfile:
            uvicorn_config.update(
                ssl_certfile=self.tls_certfile,
                ssl_keyfile=self.tls_keyfile,
            )
        return {"middleware": middleware, "uvicorn_config": uvicorn_config}


def build_network_serving_config(
    args: argparse.Namespace,
) -> NetworkServingConfig | None:
    """Build the network boundary from the standard MCP argument namespace.

    ``stdio`` has no network boundary and returns ``None``. Unknown transports,
    malformed values, and incomplete security policy raise before a listener is
    created.
    """
    inputs = resolve_network_inputs(args)
    if inputs is None:
        return None
    return NetworkServingConfig(**inputs)
