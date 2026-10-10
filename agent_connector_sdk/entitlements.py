"""Identity-scoped resource entitlement resolution.

Extracted from ``agent_utilities.security.entitlements``
(CONCEPT:AU-OS.identity.identity-scoped-resource-autoload), generalizing IdP
role inheritance from "what may I do" to "what may I *reach*": a caller's
roles/groups (:class:`agent_connector_sdk.identity.ActorContext`) determine
WHICH backend resources a connector auto-loads by default -- an operator
connects to exactly the kube contexts, SSH hosts, database connections, or
other resources their identity's roles and groups grant, with no per-server,
per-environment manual configuration.

One shared resolver lives here; a connector server supplies (a) its resource
*namespace* (``"k8s"``, ``"ssh"``, ``"mount"``...) and (b) the resources it
could offer. The resolver returns the entitled subset to auto-load.

**Capability grammar** (all interchangeable, provider-neutral):

* ``"<namespace>:<resource>"`` -- entitles that one resource (``"k8s:prod"``).
* ``"<namespace>:*"`` / ``"<namespace>:admin"`` -- entitles every resource in
  the namespace.
* ``"admin"`` / ``"system"`` (or a configured super-capability) -- entitles
  every resource in every namespace.
* a bare capability equal to a resource name -- the zero-config case: a role
  or group literally named after the resource (``"prod"``) entitles the
  ``"prod"`` resource with no namespacing needed.

**Fail-closed:** with no matching capability the entitled set is empty. A
connector decides what an empty set means (deny, or fall back to a public or
default resource) -- the resolver never invents access.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from agent_connector_sdk.identity import ActorContext, current_actor

__all__ = [
    "DEFAULT_SUPER_CAPS",
    "CatalogResource",
    "catalog_entitled_resources",
    "entitled_resources",
    "grants_all_in_namespace",
    "identity_scoped_resources",
    "is_entitled",
]

#: Capabilities that grant every resource in every namespace.
DEFAULT_SUPER_CAPS: frozenset[str] = frozenset({"admin", "system"})

#: Wildcard suffixes that, when namespaced, grant every resource in that namespace.
_NAMESPACE_WILDCARDS: frozenset[str] = frozenset({"*", "admin", "all"})


def _split_cap(cap: str) -> tuple[str, str] | None:
    """Split ``"ns:resource"`` into ``(ns, resource)``; ``None`` if bare."""
    if ":" not in cap:
        return None
    ns, _, resource = cap.partition(":")
    return ns.strip(), resource.strip()


def grants_all_in_namespace(
    capabilities: Iterable[str],
    namespace: str,
    *,
    super_caps: Iterable[str] = DEFAULT_SUPER_CAPS,
) -> bool:
    """True if ``capabilities`` grant EVERY resource in ``namespace``.

    Triggered by a super-capability (``admin``/``system``) or a namespaced
    wildcard (``"<namespace>:*"``/``":admin"``/``":all"``).
    """
    supers = set(super_caps)
    for cap in capabilities:
        if cap in supers:
            return True
        parts = _split_cap(cap)
        if parts and parts[0] == namespace and parts[1] in _NAMESPACE_WILDCARDS:
            return True
    return False


def entitled_resources(
    capabilities: Iterable[str],
    namespace: str,
    available: Iterable[str] | None = None,
    *,
    super_caps: Iterable[str] = DEFAULT_SUPER_CAPS,
) -> tuple[str, ...]:
    """Resolve which resources in ``namespace`` the caller may auto-load.

    Args:
        capabilities: the caller's roles/groups (see
            :attr:`agent_connector_sdk.identity.ActorContext.roles`).
        namespace: the connector's resource namespace, e.g. ``"k8s"``/``"ssh"``.
        available: the resources the connector could offer. When given, the
            result is the entitled subset that actually exists (order
            preserved from ``available``); a wildcard/super grant expands to
            ALL of ``available``. When ``None``, the result is exactly the
            resources named by the caller's namespaced/bare capabilities (no
            catalog to intersect against yet).
        super_caps: capabilities that grant everything (default admin/system).

    Returns:
        An order-stable tuple of entitled resource identifiers. Empty when
        nothing matches (fail-closed).
    """
    caps = list(capabilities)

    if available is not None:
        available_list = list(dict.fromkeys(available))
        if grants_all_in_namespace(caps, namespace, super_caps=super_caps):
            return tuple(available_list)
        cap_set = set(caps)
        return tuple(
            r for r in available_list if f"{namespace}:{r}" in cap_set or r in cap_set
        )

    named: list[str] = []
    for cap in caps:
        parts = _split_cap(cap)
        if parts and parts[0] == namespace and parts[1] not in _NAMESPACE_WILDCARDS:
            named.append(parts[1])
    return tuple(dict.fromkeys(named))


def is_entitled(
    capabilities: Iterable[str],
    namespace: str,
    resource: str,
    *,
    super_caps: Iterable[str] = DEFAULT_SUPER_CAPS,
) -> bool:
    """True if the caller may reach ``resource`` in ``namespace``."""
    caps = list(capabilities)
    if grants_all_in_namespace(caps, namespace, super_caps=super_caps):
        return True
    cap_set = set(caps)
    return f"{namespace}:{resource}" in cap_set or resource in cap_set


def identity_scoped_resources(
    namespace: str,
    available: Iterable[str],
    *,
    actor: ActorContext | None = None,
    super_caps: Iterable[str] = DEFAULT_SUPER_CAPS,
) -> tuple[str, ...]:
    """The one call a connector server makes to auto-load by identity.

    Resolves the bound actor (:func:`agent_connector_sdk.identity.current_actor`
    unless ``actor`` is given explicitly) to the subset of ``available``
    resources their roles/groups entitle.

    The actor must be authenticated and tenant-bound. Missing or
    caller-supplied identity fails closed before any resource catalog is
    exposed.

    Raises:
        PermissionError: the actor is unauthenticated or lacks a tenant.
    """
    ctx = actor if actor is not None else current_actor()
    actor_id = str(getattr(ctx, "actor_id", "") or "").strip()
    tenant_id = str(getattr(ctx, "tenant_id", "") or "").strip()
    if not getattr(ctx, "authenticated", False) or not actor_id or not tenant_id:
        raise PermissionError(
            "Identity-scoped resource loading requires an authenticated, tenant-bound actor"
        )
    capabilities = (*getattr(ctx, "roles", ()), *getattr(ctx, "groups", ()))
    return entitled_resources(capabilities, namespace, available, super_caps=super_caps)


@dataclass(frozen=True)
class CatalogResource:
    """One backend resource a connector's own catalog exposes.

    A connector's native catalog shape (a Keycloak realm or client, a
    systems-manager managed host, a Vaultwarden vault or collection, ...) maps
    to this one pair so :func:`catalog_entitled_resources` can resolve
    entitlements against it without the connector reimplementing the
    capability grammar (SDK-CONNECTOR-CONTROL-R036).
    """

    identifier: str
    namespace: str


def catalog_entitled_resources(
    capabilities: Iterable[str],
    catalog: Iterable[CatalogResource],
    *,
    super_caps: Iterable[str] = DEFAULT_SUPER_CAPS,
) -> tuple[str, ...]:
    """Resolve entitled identifiers across a connector's own resource catalog.

    Groups ``catalog`` by :attr:`CatalogResource.namespace` and resolves each
    namespace's entitled subset with :func:`entitled_resources`, so a
    connector with multiple resource kinds (e.g. Keycloak realms AND clients)
    gets one call instead of reimplementing the grammar per kind.

    Returns:
        An order-stable tuple of entitled identifiers, grouped by the order
        namespaces first appear in ``catalog``. Empty when nothing matches
        (fail-closed, same as :func:`entitled_resources`).
    """
    caps = list(capabilities)
    by_namespace: dict[str, list[str]] = {}
    for resource in catalog:
        by_namespace.setdefault(resource.namespace, []).append(resource.identifier)
    resolved: list[str] = []
    for namespace, identifiers in by_namespace.items():
        resolved.extend(
            entitled_resources(caps, namespace, identifiers, super_caps=super_caps)
        )
    return tuple(resolved)
