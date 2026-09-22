"""Resolve a standard MCP argument namespace into typed serving inputs."""

from __future__ import annotations

import argparse
from typing import Literal, TypedDict, cast

from agent_connector_sdk.config import csv_values, setting
from agent_connector_sdk.mcp.exposure import NetworkExposureError

__all__ = []

NETWORK_TRANSPORTS = frozenset({"streamable-http", "sse"})
DEFAULT_MAX_REQUEST_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_CONNECTIONS = 128
DEFAULT_LISTEN_BACKLOG = 256
DEFAULT_KEEPALIVE_TIMEOUT_SECONDS = 5
DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 15
DEFAULT_REQUEST_BODY_TIMEOUT_SECONDS = 30.0


class NetworkConfigInputs(TypedDict):
    transport: Literal["streamable-http", "sse"]
    host: str
    port: int
    auth_type: str
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    tls_certfile: str | None
    tls_keyfile: str | None
    tls_terminated: bool
    trusted_proxy_cidrs: tuple[str, ...]
    max_request_bytes: int
    request_body_timeout_seconds: float
    limit_concurrency: int
    backlog: int
    timeout_keep_alive: int
    timeout_graceful_shutdown: int


class _ListenerInputs(TypedDict):
    transport: Literal["streamable-http", "sse"]
    host: str
    port: int
    auth_type: str


class _SecurityInputs(TypedDict):
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    tls_certfile: str | None
    tls_keyfile: str | None
    tls_terminated: bool
    trusted_proxy_cidrs: tuple[str, ...]


class _ResourceInputs(TypedDict):
    max_request_bytes: int
    request_body_timeout_seconds: float
    limit_concurrency: int
    backlog: int
    timeout_keep_alive: int
    timeout_graceful_shutdown: int


def bounded_int(value: object, *, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        raise NetworkExposureError(f"{name} must be an integer") from None
    if not minimum <= parsed <= maximum:
        raise NetworkExposureError(f"{name} is outside the safe range")
    return parsed


def bounded_float(value: object, *, name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        raise NetworkExposureError(f"{name} must be numeric") from None
    if not minimum <= parsed <= maximum:
        raise NetworkExposureError(f"{name} is outside the safe range")
    return parsed


def _argument_or_setting(
    args: argparse.Namespace,
    *,
    attribute: str,
    setting_name: str,
    default: int | float,
) -> object:
    configured = getattr(args, attribute, None)
    if configured is not None and configured != "":
        return configured
    configured = setting(setting_name)
    return default if configured is None else configured


def _resource_inputs(args: argparse.Namespace) -> _ResourceInputs:
    def configured(attribute: str, setting_name: str, default: int | float) -> object:
        return _argument_or_setting(
            args,
            attribute=attribute,
            setting_name=setting_name,
            default=default,
        )

    return _ResourceInputs(
        max_request_bytes=bounded_int(
            configured(
                "max_request_bytes", "MCP_MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES
            ),
            name="MCP_MAX_REQUEST_BYTES",
            minimum=1_024,
            maximum=256 * 1024 * 1024,
        ),
        request_body_timeout_seconds=bounded_float(
            configured(
                "request_body_timeout_seconds",
                "MCP_REQUEST_BODY_TIMEOUT_SECONDS",
                DEFAULT_REQUEST_BODY_TIMEOUT_SECONDS,
            ),
            name="MCP_REQUEST_BODY_TIMEOUT_SECONDS",
            minimum=1.0,
            maximum=300.0,
        ),
        limit_concurrency=bounded_int(
            configured(
                "max_connections", "MCP_MAX_CONNECTIONS", DEFAULT_MAX_CONNECTIONS
            ),
            name="MCP_MAX_CONNECTIONS",
            minimum=1,
            maximum=10_000,
        ),
        backlog=bounded_int(
            configured("listen_backlog", "MCP_LISTEN_BACKLOG", DEFAULT_LISTEN_BACKLOG),
            name="MCP_LISTEN_BACKLOG",
            minimum=1,
            maximum=65_535,
        ),
        timeout_keep_alive=bounded_int(
            configured(
                "keepalive_timeout_seconds",
                "MCP_KEEPALIVE_TIMEOUT_SECONDS",
                DEFAULT_KEEPALIVE_TIMEOUT_SECONDS,
            ),
            name="MCP_KEEPALIVE_TIMEOUT_SECONDS",
            minimum=1,
            maximum=300,
        ),
        timeout_graceful_shutdown=bounded_int(
            configured(
                "graceful_shutdown_timeout_seconds",
                "MCP_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS",
                DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
            ),
            name="MCP_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS",
            minimum=1,
            maximum=300,
        ),
    )


def resolve_network_inputs(args: argparse.Namespace) -> NetworkConfigInputs | None:
    transport = str(getattr(args, "transport", "") or "").lower()
    if transport == "stdio":
        return None
    if transport not in NETWORK_TRANSPORTS:
        raise NetworkExposureError("unsupported MCP transport")
    return NetworkConfigInputs(
        **_listener_inputs(args, transport),
        **_security_inputs(args),
        **_resource_inputs(args),
    )


def _listener_inputs(args: argparse.Namespace, transport: str) -> _ListenerInputs:
    return _ListenerInputs(
        transport=cast(Literal["streamable-http", "sse"], transport),
        host=str(getattr(args, "host", "") or ""),
        port=bounded_int(
            getattr(args, "port", -1), name="port", minimum=0, maximum=65_535
        ),
        auth_type=str(getattr(args, "auth_type", "none") or "none").lower(),
    )


def _security_inputs(args: argparse.Namespace) -> _SecurityInputs:
    return _SecurityInputs(
        allowed_hosts=tuple(csv_values(getattr(args, "allowed_hosts", ""))),
        allowed_origins=tuple(csv_values(getattr(args, "allowed_origins", ""))),
        tls_certfile=str(getattr(args, "tls_certfile", "") or "") or None,
        tls_keyfile=str(getattr(args, "tls_keyfile", "") or "") or None,
        tls_terminated=bool(getattr(args, "tls_terminated", False)),
        trusted_proxy_cidrs=tuple(csv_values(getattr(args, "trusted_proxy_cidrs", ""))),
    )
