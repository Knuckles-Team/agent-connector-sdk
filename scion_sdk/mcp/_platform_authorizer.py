"""Verified-scope admission for platform fallback tools."""

from __future__ import annotations

from typing import Any

from scion_sdk.adapters.platform_backend import PlatformAuthorizer
from scion_sdk.adapters.platform_models import PlatformCapability, PlatformRequest
from scion_sdk.identity import ActorContext

_TENANT_CLAIM_NAMES = ("tenant_id", "tenant", "org_id", "tid", "org")


def _token_tenants(claims: dict[str, Any]) -> set[str]:
    return {
        value.strip()
        for name in _TENANT_CLAIM_NAMES
        if isinstance((value := claims.get(name)), str) and value.strip()
    }


def _token_scopes(token: Any, claims: dict[str, Any]) -> set[str]:
    scopes = {scope for scope in token.scopes if isinstance(scope, str)}
    scope_claim = claims.get("scope")
    if isinstance(scope_claim, str):
        scopes.update(scope_claim.split())
    return scopes


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
        admitted = (
            isinstance(subject, str)
            and subject == actor.actor_id
            and _token_tenants(claims) == {actor.tenant_id}
            and capability.required_scope in _token_scopes(token, claims)
        )
        if not admitted:
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
