"""Identity-scoped resources: which backend resources a caller may reach.

Replaces ``agent_utilities.security.entitlements``. A connector names its
resource namespace (``"k8s"``, ``"ssh"``, ``"db"`` ...) and the resources it could
offer; the caller's roles decide the entitled subset.

Capability grammar (provider neutral; Okta groups and Keycloak roles alike):

* ``"<namespace>:<resource>"`` entitles one resource;
* ``"<namespace>:*"``, ``"<namespace>:admin"`` or ``"<namespace>:all"`` entitle
  every resource in the namespace;
* ``"admin"`` or ``"system"`` entitle everything;
* a bare capability equal to a resource name entitles that resource.

Nothing matching means nothing entitled: the resolver never invents access.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from fastmcp.server.dependencies import get_access_token

from agent_connector_sdk.identity import (
    ActorContext,
    ActorType,
    IdentityRequiredError,
    current_actor,
)

__all__ = [
    "DEFAULT_SUPER_CAPABILITIES",
    "entitled_resources",
    "grants_all_in_namespace",
    "identity_scoped_resources",
    "is_entitled",
    "verified_actor",
]

#: Capabilities that entitle every resource in every namespace.
DEFAULT_SUPER_CAPABILITIES: frozenset[str] = frozenset({"admin", "system"})
_NAMESPACE_WILDCARDS = frozenset({"*", "admin", "all"})


def _split(capability: str) -> tuple[str, str] | None:
    if ":" not in capability:
        return None
    namespace, _, resource = capability.partition(":")
    return namespace.strip(), resource.strip()


def grants_all_in_namespace(
    capabilities: Iterable[str],
    namespace: str,
    *,
    super_capabilities: Iterable[str] = DEFAULT_SUPER_CAPABILITIES,
) -> bool:
    """Whether ``capabilities`` entitle every resource in ``namespace``."""
    supers = frozenset(super_capabilities)
    for capability in capabilities:
        parts = _split(capability)
        if capability in supers or (
            parts is not None
            and parts[0] == namespace
            and parts[1] in _NAMESPACE_WILDCARDS
        ):
            return True
    return False


def is_entitled(
    capabilities: Iterable[str],
    namespace: str,
    resource: str,
    *,
    super_capabilities: Iterable[str] = DEFAULT_SUPER_CAPABILITIES,
) -> bool:
    """Whether the caller may reach ``resource`` in ``namespace``."""
    held = list(capabilities)
    if grants_all_in_namespace(held, namespace, super_capabilities=super_capabilities):
        return True
    return f"{namespace}:{resource}" in held or resource in held


def _named(capabilities: Iterable[str], namespace: str) -> tuple[str, ...]:
    named = [
        parts[1]
        for parts in map(_split, capabilities)
        if parts is not None
        and parts[0] == namespace
        and parts[1] not in _NAMESPACE_WILDCARDS
    ]
    return tuple(dict.fromkeys(named))


def entitled_resources(
    capabilities: Iterable[str],
    namespace: str,
    available: Iterable[str] | None = None,
    *,
    super_capabilities: Iterable[str] = DEFAULT_SUPER_CAPABILITIES,
) -> tuple[str, ...]:
    """The entitled subset of ``available`` (order kept), or the named resources.

    With ``available`` omitted, the result is exactly the resources the
    namespaced capabilities name.
    """
    held = list(capabilities)
    if available is None:
        return _named(held, namespace)
    offered = list(dict.fromkeys(available))
    return tuple(
        resource
        for resource in offered
        if is_entitled(held, namespace, resource, super_capabilities=super_capabilities)
    )


def _claim_list(claims: Mapping[str, Any], name: str) -> list[str]:
    value = claims.get(name)
    if isinstance(value, str):
        return value.split()
    return [str(item) for item in value] if isinstance(value, list) else []


def _roles(claims: Mapping[str, Any]) -> tuple[str, ...]:
    realm = claims.get("realm_access")
    realm_roles = _claim_list(realm, "roles") if isinstance(realm, Mapping) else []
    roles = [
        *_claim_list(claims, "roles"),
        *_claim_list(claims, "groups"),
        *realm_roles,
    ]
    return tuple(dict.fromkeys(roles))


def verified_actor() -> ActorContext:
    """The bound actor, else the caller of the verified MCP access token.

    Raises:
        IdentityRequiredError: no actor is bound and no verified token is present.
    """
    try:
        return current_actor()
    except IdentityRequiredError:
        token = get_access_token()
    if token is None:
        raise IdentityRequiredError("a verified caller identity is required")
    claims = token.claims or {}
    return ActorContext(
        actor_id=str(claims.get("sub") or token.client_id),
        actor_type=ActorType.HUMAN
        if claims.get("sub")
        else ActorType.AUTOMATED_SERVICE,
        tenant_id=str(claims.get("tenant") or claims.get("tenant_id") or ""),
        roles=_roles(claims),
        groups=tuple(_claim_list(claims, "groups")),
        authenticated=True,
    )


def identity_scoped_resources(
    namespace: str,
    available: Iterable[str],
    *,
    actor: ActorContext | None = None,
    super_capabilities: Iterable[str] = DEFAULT_SUPER_CAPABILITIES,
) -> tuple[str, ...]:
    """The resources in ``namespace`` the verified caller may auto-load.

    Raises:
        IdentityRequiredError: the caller is not authenticated or not tenant-bound.
    """
    ctx = actor if actor is not None else verified_actor()
    if not ctx.authenticated or not ctx.tenant_id:
        raise IdentityRequiredError(
            "identity-scoped resources need an authenticated, tenant-bound caller"
        )
    return entitled_resources(
        ctx.roles, namespace, available, super_capabilities=super_capabilities
    )
