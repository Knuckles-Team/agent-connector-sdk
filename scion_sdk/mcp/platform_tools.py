"""Register authenticated read, search and status tools for platform fallback."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from scion_sdk.adapters.platform_backend import PlatformAuthorizer
from scion_sdk.adapters.platform_fallback import PlatformFallback, _refused
from scion_sdk.adapters.platform_models import (
    PlatformCapability,
    PlatformRequest,
    PlatformResult,
)
from scion_sdk.identity import (
    ActorContext,
    current_actor,
)
from scion_sdk.mcp.action_dispatch import dispatch_async


class _PlatformToolClient:
    def __init__(self, fallback: PlatformFallback) -> None:
        self._fallback = fallback

    async def read(self, request: PlatformRequest) -> PlatformResult:
        return await self._execute(request, "read")

    async def search(self, request: PlatformRequest) -> PlatformResult:
        return await self._execute(request, "search")

    async def status(self, request: PlatformRequest) -> Any:
        actor = current_actor()
        result = await self._fallback.status(actor, request)
        return result.model_dump(mode="json") if result is not None else None

    async def _execute(
        self, request: PlatformRequest, operation: str
    ) -> PlatformResult:
        if request.operation != operation:
            return _refused(request, "invalid_request")
        actor = current_actor()
        return await self._fallback.execute(actor, request)


def register_platform_tools(server: FastMCP, fallback: PlatformFallback) -> None:
    """Add connector read/search/status tools using the standard dispatcher.

    A connector may call this from a ``register_tool_surface`` registrar. It
    supplies the host-authorized fallback and backend admission ports.
    """
    from scion_sdk.mcp.tool_surface import registered_tools

    if {"platform_read", "platform_search", "platform_status"} & registered_tools(
        server
    ).keys():
        raise ValueError("platform tool name already registered")
    client = _PlatformToolClient(fallback)

    @server.tool(name="platform_read")
    async def platform_read(request: PlatformRequest) -> dict[str, Any]:
        result = await dispatch_async(client, "read", {"request": request})
        if not isinstance(result, PlatformResult):
            raise RuntimeError("platform dispatcher returned an invalid result")
        return result.model_dump(mode="json")

    @server.tool(name="platform_search")
    async def platform_search(request: PlatformRequest) -> dict[str, Any]:
        result = await dispatch_async(client, "search", {"request": request})
        if not isinstance(result, PlatformResult):
            raise RuntimeError("platform dispatcher returned an invalid result")
        return result.model_dump(mode="json")

    @server.tool(name="platform_status")
    async def platform_status(request: PlatformRequest) -> Any:
        return await dispatch_async(client, "status", {"request": request})


class VerifiedScopeAuthorizer:
    """Require the current verified MCP token's identity and capability scope.

    The injected delegate remains responsible for connector policy and
    continuation authentication. This wrapper never interprets caller-supplied
    request fields as evidence of authentication.
    """

    def __init__(self, delegate: PlatformAuthorizer) -> None:
        self._delegate = delegate

    async def authorize(
        self,
        actor: ActorContext,
        request: PlatformRequest,
        capability: PlatformCapability,
    ) -> bool:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
        if token is None:
            return False
        claims = token.claims if isinstance(token.claims, dict) else {}
        subject = claims.get("sub") or token.client_id
        tenants = {
            value.strip()
            for name in ("tenant_id", "tenant", "org_id", "tid", "org")
            if isinstance((value := claims.get(name)), str) and value.strip()
        }
        scopes = {scope for scope in token.scopes if isinstance(scope, str)}
        scope_claim = claims.get("scope")
        if isinstance(scope_claim, str):
            scopes.update(scope_claim.split())
        if (
            not isinstance(subject, str)
            or subject != actor.actor_id
            or tenants != {actor.tenant_id}
            or capability.required_scope not in scopes
        ):
            return False
        return await self._delegate.authorize(actor, request, capability)

    async def verify_continuation(
        self,
        actor: ActorContext,
        request: PlatformRequest,
        capability: PlatformCapability,
    ) -> bool:
        if not await self.authorize(actor, request, capability):
            return False
        return await self._delegate.verify_continuation(actor, request, capability)
