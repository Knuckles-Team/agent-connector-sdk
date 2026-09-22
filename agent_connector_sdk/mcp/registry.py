"""Fleet self-registration: renew this server's lease in the server registry.

Extracted from the ``RegisterServer`` lease loop in
``agent_utilities.mcp.server_factory``. AU reached the engine through its own
``GraphComputeEngine`` singleton; here the registry is a port, and
:class:`EpistemicGraphServerRegistry` adapts an ``epistemic_graph`` client that
exposes ``server_registry.register``. A client that predates ``RegisterServer``
(including epistemic-graph 2.23.0) is refused at construction instead of
failing silently on every heartbeat. Epistemic-graph 2.27.0 is the SDK's first
compatible client contract.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any, NoReturn, Protocol

from agent_connector_sdk.config import setting

__all__ = [
    "DEFAULT_LEASE_TTL_SECONDS",
    "MIN_LEASE_TTL_SECONDS",
    "EpistemicGraphServerRegistry",
    "ServerRegistry",
    "ServerRegistryUnavailableError",
    "endpoint_reference",
    "lease_ttl_seconds",
    "maintain_registration",
    "registration_lifespan",
]

_logger = logging.getLogger(__name__)

DEFAULT_LEASE_TTL_SECONDS = 300
MIN_LEASE_TTL_SECONDS = 60
_NETWORK_TRANSPORTS = frozenset({"streamable-http", "sse"})


class ServerRegistry(Protocol):
    """Push-registers a server identity with a lease."""

    async def register(
        self,
        name: str,
        url: str,
        *,
        resources: Mapping[str, Any] | None,
        ttl_secs: int,
    ) -> bool:
        """Register or renew ``name``; ``True`` on success."""
        ...


class ServerRegistryUnavailableError(RuntimeError):
    """The supplied client cannot register servers."""


class EpistemicGraphServerRegistry:
    """Adapts an ``epistemic_graph`` client's ``server_registry`` namespace."""

    def __init__(self, client: object) -> None:
        namespace = getattr(client, "server_registry", None)
        if not callable(getattr(namespace, "register", None)):
            raise ServerRegistryUnavailableError(
                "this epistemic-graph client does not expose RegisterServer"
            )
        self._namespace: Any = namespace

    async def register(
        self,
        name: str,
        url: str,
        *,
        resources: Mapping[str, Any] | None,
        ttl_secs: int,
    ) -> bool:
        """Delegate to ``client.server_registry.register``."""
        result = await self._namespace.register(
            name, url, resources=dict(resources or {}), ttl_secs=ttl_secs
        )
        return bool(result)


def lease_ttl_seconds() -> int:
    """``MCP_FLEET_REGISTRATION_TTL_SECS``, never below the minimum lease."""
    value = setting("MCP_FLEET_REGISTRATION_TTL_SECS", DEFAULT_LEASE_TTL_SECONDS)
    if not isinstance(value, int) or value < MIN_LEASE_TTL_SECONDS:
        return DEFAULT_LEASE_TTL_SECONDS
    return value


def endpoint_reference(name: str, *, transport: str, host: str, port: int) -> str:
    """A privacy-safe reference to how the server is reached (never credentials)."""
    if transport in _NETWORK_TRANSPORTS:
        return f"{transport}://{host}:{port}"
    return f"stdio://{name}"


async def _heartbeat(
    registry: ServerRegistry,
    name: str,
    url: str,
    *,
    ttl_secs: int,
    resources: Mapping[str, Any] | None,
) -> None:
    try:
        accepted = await registry.register(
            name, url, resources=resources, ttl_secs=ttl_secs
        )
    except Exception as exc:  # retried on the next heartbeat by design
        _logger.warning(
            "Fleet self-registration failed; retrying: %s",
            exc,
        )
        return
    if not accepted:
        _logger.warning("Fleet registry refused registration for %s", name)


async def maintain_registration(
    registry: ServerRegistry,
    name: str,
    url: str,
    *,
    ttl_secs: int,
    resources: Mapping[str, Any] | None = None,
    interval_seconds: float | None = None,
) -> NoReturn:
    """Register, then renew forever at a third of the TTL.

    A failed attempt is logged and retried on the same cadence, so a server
    that starts before the registry is reachable registers once it is.
    """
    interval = interval_seconds or max(1, ttl_secs // 3)
    while True:
        await _heartbeat(registry, name, url, ttl_secs=ttl_secs, resources=resources)
        await asyncio.sleep(interval)


def registration_lifespan(
    registry: ServerRegistry, *, name: str, url: str, ttl_secs: int
) -> Callable[[Any], AbstractAsyncContextManager[None]]:
    """Build a FastMCP lifespan that runs :func:`maintain_registration`."""

    @contextlib.asynccontextmanager
    async def _lifespan(_app: Any) -> AsyncIterator[None]:
        task = asyncio.create_task(
            maintain_registration(registry, name, url, ttl_secs=ttl_secs)
        )
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return _lifespan
