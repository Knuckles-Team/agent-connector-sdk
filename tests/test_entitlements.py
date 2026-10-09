"""Identity-scoped resource entitlement resolution (SDK-CONNECTOR-CONTROL-R025)."""

from __future__ import annotations

import pytest

from agent_connector_sdk.entitlements import (
    DEFAULT_SUPER_CAPS,
    entitled_resources,
    grants_all_in_namespace,
    identity_scoped_resources,
    is_entitled,
)
from agent_connector_sdk.identity import ActorContext, ActorType, use_actor


def _actor(
    *,
    roles: tuple[str, ...] = (),
    groups: tuple[str, ...] = (),
    authenticated: bool = True,
    tenant_id: str = "tenant-1",
) -> ActorContext:
    return ActorContext(
        actor_id="caller-1",
        actor_type=ActorType.HUMAN,
        tenant_id=tenant_id,
        roles=roles,
        groups=groups,
        authenticated=authenticated,
    )


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R025")
def test_namespaced_capability_entitles_one_resource() -> None:
    assert entitled_resources(["k8s:prod"], "k8s", ["prod", "staging"]) == ("prod",)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R025")
def test_bare_capability_entitles_the_zero_config_resource() -> None:
    assert entitled_resources(["prod"], "k8s", ["prod", "staging"]) == ("prod",)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R025")
def test_namespace_wildcard_grants_every_available_resource() -> None:
    assert entitled_resources(["k8s:*"], "k8s", ["prod", "staging"]) == (
        "prod",
        "staging",
    )


def test_super_capability_grants_every_namespace() -> None:
    assert grants_all_in_namespace(["admin"], "ssh")
    assert entitled_resources(["system"], "ssh", ["host-a", "host-b"]) == (
        "host-a",
        "host-b",
    )


def test_no_matching_capability_is_fail_closed() -> None:
    assert entitled_resources(["k8s:staging"], "k8s", ["prod"]) == ()
    assert entitled_resources([], "k8s", ["prod"]) == ()


def test_without_a_catalog_resolves_named_resources_directly() -> None:
    assert entitled_resources(["k8s:prod", "k8s:staging", "ssh:host-a"], "k8s") == (
        "prod",
        "staging",
    )


def test_is_entitled_checks_one_resource() -> None:
    assert is_entitled(["k8s:prod"], "k8s", "prod")
    assert not is_entitled(["k8s:prod"], "k8s", "staging")
    assert is_entitled(["admin"], "k8s", "anything", super_caps=DEFAULT_SUPER_CAPS)


def test_identity_scoped_resources_resolves_the_bound_actor() -> None:
    with use_actor(_actor(roles=("k8s:prod",))):
        assert identity_scoped_resources("k8s", ["prod", "staging"]) == ("prod",)


def test_identity_scoped_resources_combines_roles_and_groups() -> None:
    actor = _actor(roles=("k8s:prod",), groups=("ssh:host-a",))
    assert identity_scoped_resources("ssh", ["host-a", "host-b"], actor=actor) == (
        "host-a",
    )


def test_identity_scoped_resources_rejects_an_unauthenticated_actor() -> None:
    actor = _actor(roles=("k8s:prod",), authenticated=False)
    with pytest.raises(PermissionError):
        identity_scoped_resources("k8s", ["prod"], actor=actor)


def test_identity_scoped_resources_rejects_a_tenant_less_actor() -> None:
    actor = _actor(roles=("k8s:prod",), tenant_id="")
    with pytest.raises(PermissionError):
        identity_scoped_resources("k8s", ["prod"], actor=actor)


def test_identity_scoped_resources_requires_a_bound_actor_when_none_is_passed() -> None:
    from agent_connector_sdk.identity import IdentityRequiredError

    with pytest.raises(IdentityRequiredError):
        identity_scoped_resources("k8s", ["prod"])
