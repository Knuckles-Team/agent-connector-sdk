"""Identity-scoped resource resolution fails closed and never invents access."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastmcp.server.auth import AccessToken as FastMcpAccessToken
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

from agent_connector_sdk.entitlements import (
    DEFAULT_SUPER_CAPABILITIES,
    entitled_resources,
    grants_all_in_namespace,
    identity_scoped_resources,
    is_entitled,
    verified_actor,
)
from agent_connector_sdk.identity import (
    ActorContext,
    ActorType,
    IdentityRequiredError,
    use_actor,
)

CONTEXTS = ("dev", "prod", "lab")


def _token(claims: dict[str, object]) -> Iterator[None]:
    access = FastMcpAccessToken(token="t", client_id="ide", scopes=[], claims=claims)
    reset = auth_context_var.set(AuthenticatedUser(access))
    yield
    auth_context_var.reset(reset)


@pytest.fixture
def keycloak_caller() -> Iterator[None]:
    yield from _token(
        {
            "sub": "alice",
            "tenant": "acme",
            "realm_access": {"roles": ["k8s:prod"]},
            "groups": ["lab"],
        }
    )


def test_capability_grammar() -> None:
    assert entitled_resources(["k8s:prod", "lab"], "k8s", CONTEXTS) == ("prod", "lab")
    assert entitled_resources(["k8s:*"], "k8s", CONTEXTS) == CONTEXTS
    assert entitled_resources(["admin"], "k8s", CONTEXTS) == CONTEXTS
    assert entitled_resources(["ssh:prod"], "k8s", CONTEXTS) == ()
    assert entitled_resources(["k8s:dev", "k8s:all", "k8s:dev"], "k8s") == ("dev",)
    assert grants_all_in_namespace(["system"], "db")
    assert "admin" in DEFAULT_SUPER_CAPABILITIES
    assert is_entitled(["k8s:prod"], "k8s", "prod")
    assert not is_entitled(["k8s:prod"], "k8s", "dev", super_capabilities=())


def test_verified_token_is_the_ambient_actor(keycloak_caller: None) -> None:
    actor = verified_actor()
    assert actor.authenticated and actor.tenant_id == "acme"
    assert actor.actor_type is ActorType.HUMAN
    assert identity_scoped_resources("k8s", CONTEXTS) == ("prod", "lab")


def test_bound_actor_wins_and_must_be_tenant_bound() -> None:
    bound = ActorContext(
        "svc", ActorType.AUTOMATED_SERVICE, "acme", ("k8s:dev",), (), True
    )
    with use_actor(bound):
        assert identity_scoped_resources("k8s", CONTEXTS) == ("dev",)
    unbound = ActorContext("svc", ActorType.AUTOMATED_SERVICE, "", ("admin",), (), True)
    with pytest.raises(IdentityRequiredError, match="tenant-bound"):
        identity_scoped_resources("k8s", CONTEXTS, actor=unbound)


def test_no_identity_fails_closed() -> None:
    with pytest.raises(IdentityRequiredError, match="verified caller"):
        identity_scoped_resources("k8s", CONTEXTS)
