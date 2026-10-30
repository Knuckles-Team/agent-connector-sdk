"""Bind the request's actor once, in the served MCP stack.

This is the one actor-resolution path for every tool call, whatever the
transport. Every connector built by :func:`scion_sdk.mcp.server.create_mcp_server`
gets this middleware on stdio and on streamable HTTP alike, configured the same
way. A server without it resolves the same actor lazily through
:func:`scion_sdk.identity.current_actor`, so no bootstrap ``use_actor`` call is
ever needed.

The transport only supplies the credential; :func:`request_actor` turns it into
an actor, and tools and entitlements read that actor and never the transport:

* a local transport (stdio or an in-process client) is the trusted local
  principal, :data:`~scion_sdk.identity.SYSTEM_ACTOR`;
* an HTTP request carries the principal its verified access token names, with
  the IdP's roles and groups (generic, Okta and Keycloak claim locations);
* an HTTP request to a server the operator started with auth type ``none``
  carries no credential and is the same trusted local principal as stdio,
  :data:`~scion_sdk.identity.SYSTEM_ACTOR`;
* an HTTP request without a verified token to any other server binds
  :data:`~scion_sdk.identity.ANONYMOUS_ACTOR`, which holds no entitlements. A
  factory server with an auth provider answers such a request 401 first.

An :class:`~scion_sdk.identity.IdentityRequiredError` raised under the
binding reaches the client as a typed refusal, never as an internal error.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from fastmcp.server.dependencies import get_access_token, get_http_request
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.shared.exceptions import MCPError

from scion_sdk.config import csv_values, setting
from scion_sdk.identity import (
    ANONYMOUS_ACTOR,
    SYSTEM_ACTOR,
    ActorContext,
    ActorType,
    IdentityRequiredError,
    use_actor,
)

__all__ = [
    "PRINCIPAL_GRANTS_SETTING",
    "ActorBindingMiddleware",
    "request_actor",
    "token_actor",
]

#: Operator config granting capabilities to token principals, for example
#: ``arbora=ssh:*;backup-bot=ssh:nas,ssh:lab``. A principal matches the token's
#: ``sub``, ``client_id``, ``azp`` or ``preferred_username``.
PRINCIPAL_GRANTS_SETTING = "CONNECTOR_PRINCIPAL_GRANTS"

#: JSON-RPC server error code for an identity refusal (the code FastMCP uses
#: for a permission denial).
IDENTITY_REFUSAL_CODE = -32000

_ROLE_KEYS = ("roles", "role")
_GROUP_KEYS = ("groups", "group")
_TENANT_KEYS = ("tenant_id", "tenant", "org_id", "tid", "org")
_SUBJECT_KEYS = ("sub", "client_id", "azp")
_PRINCIPAL_KEYS = (*_SUBJECT_KEYS, "preferred_username")


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


def _configured_grants(claims: Mapping[str, Any], client_id: object) -> list[str]:
    """Capabilities ``CONNECTOR_PRINCIPAL_GRANTS`` gives the token's principal."""
    names = {str(client_id or "").strip()}
    names.update(name for key in _PRINCIPAL_KEYS for name in _strings(claims.get(key)))
    names.discard("")
    grants: list[str] = []
    for entry in str(setting(PRINCIPAL_GRANTS_SETTING, "") or "").split(";"):
        principal, _, capabilities = entry.partition("=")
        if principal.strip() in names:
            grants.extend(csv_values(capabilities))
    return grants


def token_actor(token: Any) -> ActorContext:
    """The authenticated actor a verified access token names.

    The only place a token becomes an actor: the served security profile and the
    request binding both read it, so they cannot disagree about who is calling.
    """
    claims = token.claims if isinstance(token.claims, Mapping) else {}
    subject = next(
        (claims[key] for key in _SUBJECT_KEYS if _strings(claims.get(key))),
        token.client_id,
    )
    tenant = next(
        (claims[key] for key in _TENANT_KEYS if _strings(claims.get(key))),
        claims.get("iss") or "",
    )
    groups = [
        group.strip("/") for key in _GROUP_KEYS for group in _strings(claims.get(key))
    ]
    return ActorContext(
        actor_id=str(subject).strip(),
        actor_type=ActorType.HUMAN,
        tenant_id=str(tenant).strip(),
        roles=tuple(
            dict.fromkeys(
                [*_roles(claims), *_configured_grants(claims, token.client_id)]
            )
        ),
        groups=tuple(dict.fromkeys(group for group in groups if group)),
        authenticated=True,
    )


def request_actor(*, no_auth: bool = False) -> ActorContext:
    """The actor for the current MCP request, from the credential its transport carries.

    Args:
        no_auth: The operator started the server with auth type ``none``: no
            request carries a credential, so each is the trusted local principal.
    """
    try:
        get_http_request()
    except RuntimeError:
        return SYSTEM_ACTOR
    token = get_access_token()
    if token is None:
        return SYSTEM_ACTOR if no_auth else ANONYMOUS_ACTOR
    return token_actor(token)


def _identity_error(error: BaseException) -> IdentityRequiredError | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, IdentityRequiredError):
            return current
        seen.add(id(current))
        current = current.__cause__
    return None


async def _call_typed(context: MiddlewareContext[Any], call_next: Any) -> Any:
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


class ActorBindingMiddleware(Middleware):
    """Bind :func:`request_actor` around every request; refuse identity errors typed.

    ``no_auth`` is true when the operator chose auth type ``none``.
    """

    def __init__(self, *, no_auth: bool = False) -> None:
        self.no_auth = no_auth

    async def on_request(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        with use_actor(request_actor(no_auth=self.no_auth)):
            return await _call_typed(context, call_next)
