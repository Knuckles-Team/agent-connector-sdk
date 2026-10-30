"""Bind the request's actor once, in the served MCP stack.

Every connector built by :func:`scion_sdk.mcp.server.create_mcp_server`
gets this middleware. A server without it resolves the same actor lazily through
:func:`scion_sdk.identity.current_actor`, so no bootstrap ``use_actor`` call is
ever needed:

* a local transport (stdio or an in-process client) binds
  :data:`~scion_sdk.identity.SYSTEM_ACTOR`;
* an authenticated HTTP request binds the actor its verified token names, with
  the IdP's roles and groups (generic, Okta and Keycloak claim locations);
* an unauthenticated HTTP request binds
  :data:`~scion_sdk.identity.ANONYMOUS_ACTOR`, which holds no
  entitlements.

An :class:`~scion_sdk.identity.IdentityRequiredError` raised under the
binding reaches the client as a typed refusal, never as an internal error.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from fastmcp.server.dependencies import get_access_token, get_http_request
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.shared.exceptions import MCPError

from scion_sdk.identity import (
    ANONYMOUS_ACTOR,
    SYSTEM_ACTOR,
    ActorContext,
    ActorType,
    IdentityRequiredError,
    use_actor,
)

__all__ = ["ActorBindingMiddleware", "request_actor"]

#: JSON-RPC server error code for an identity refusal (the code FastMCP uses
#: for a permission denial).
IDENTITY_REFUSAL_CODE = -32000

_ROLE_KEYS = ("roles", "role")
_GROUP_KEYS = ("groups", "group")
_TENANT_KEYS = ("tenant_id", "tenant", "org_id", "tid", "org")
_SUBJECT_KEYS = ("sub", "client_id", "azp")


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def _roles(claims: Mapping[str, Any]) -> list[str]:
    roles = [role for key in _ROLE_KEYS for role in _strings(claims.get(key))]
    realm = claims.get("realm_access")
    if isinstance(realm, Mapping):
        roles.extend(_strings(realm.get("roles")))
    clients = claims.get("resource_access")
    if isinstance(clients, Mapping):
        for block in clients.values():
            if isinstance(block, Mapping):
                roles.extend(_strings(block.get("roles")))
    return roles


def _actor_from_token(token: Any) -> ActorContext:
    """The authenticated actor a verified access token names."""
    claims = token.claims if isinstance(token.claims, Mapping) else {}
    subject = next(
        (claims[key] for key in _SUBJECT_KEYS if _strings(claims.get(key))),
        token.client_id,
    )
    tenant = next(
        (claims[key] for key in _TENANT_KEYS if _strings(claims.get(key))), ""
    )
    groups = [
        group.strip("/") for key in _GROUP_KEYS for group in _strings(claims.get(key))
    ]
    return ActorContext(
        actor_id=str(subject).strip(),
        actor_type=ActorType.HUMAN,
        tenant_id=str(tenant).strip(),
        roles=tuple(dict.fromkeys(_roles(claims))),
        groups=tuple(dict.fromkeys(group for group in groups if group)),
        authenticated=True,
    )


def request_actor() -> ActorContext:
    """The actor for the current MCP request, by transport and credential."""
    try:
        get_http_request()
    except RuntimeError:
        return SYSTEM_ACTOR
    token = get_access_token()
    if token is None:
        return ANONYMOUS_ACTOR
    return _actor_from_token(token)


def _identity_error(error: BaseException) -> IdentityRequiredError | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, IdentityRequiredError):
            return current
        seen.add(id(current))
        current = current.__cause__
    return None


class ActorBindingMiddleware(Middleware):
    """Bind :func:`request_actor` around every request; refuse identity errors typed."""

    async def on_request(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        with use_actor(request_actor()):
            try:
                return await call_next(context)
            except Exception as error:
                refusal = _identity_error(error)
                if refusal is None:
                    raise
                raise MCPError(
                    IDENTITY_REFUSAL_CODE,
                    f"{refusal.reason}: {refusal}",
                    {"reason": refusal.reason},
                ) from error
