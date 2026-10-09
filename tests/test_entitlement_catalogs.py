"""SDK-CONNECTOR-CONTROL-R036: entitlements over connector resource catalogs."""

from __future__ import annotations

from agent_connector_sdk.entitlements import CatalogResource, catalog_entitled_resources

_KEYCLOAK_CATALOG = (
    CatalogResource(identifier="realm-prod", namespace="keycloak-realm"),
    CatalogResource(identifier="realm-staging", namespace="keycloak-realm"),
    CatalogResource(identifier="client-webui", namespace="keycloak-client"),
)

_SYSTEMS_MANAGER_CATALOG = (
    CatalogResource(identifier="host-a", namespace="managed-host"),
    CatalogResource(identifier="host-b", namespace="managed-host"),
)

_VAULTWARDEN_CATALOG = (
    CatalogResource(identifier="vault-ops", namespace="vault"),
    CatalogResource(identifier="collection-prod-secrets", namespace="collection"),
)


def test_keycloak_shaped_catalog_resolves_matching_subset() -> None:
    caps = ["keycloak-realm:realm-prod", "keycloak-client:client-webui"]
    assert catalog_entitled_resources(caps, _KEYCLOAK_CATALOG) == (
        "realm-prod",
        "client-webui",
    )


def test_systems_manager_shaped_catalog_resolves_matching_subset() -> None:
    assert catalog_entitled_resources(
        ["managed-host:host-b"], _SYSTEMS_MANAGER_CATALOG
    ) == ("host-b",)


def test_vaultwarden_shaped_catalog_resolves_matching_subset() -> None:
    assert catalog_entitled_resources(["vault:vault-ops"], _VAULTWARDEN_CATALOG) == (
        "vault-ops",
    )


def test_unmatched_capability_resolves_empty_fail_closed() -> None:
    assert catalog_entitled_resources(["managed-host:host-z"], _SYSTEMS_MANAGER_CATALOG) == ()
    assert catalog_entitled_resources([], _KEYCLOAK_CATALOG) == ()


def test_super_capability_grants_every_namespace_in_catalog() -> None:
    assert catalog_entitled_resources(["admin"], _KEYCLOAK_CATALOG) == (
        "realm-prod",
        "realm-staging",
        "client-webui",
    )
