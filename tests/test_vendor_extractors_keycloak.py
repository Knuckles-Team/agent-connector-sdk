"""SDK-SOURCE-INGEST-R006.14: the Keycloak vendor extractor port."""

from __future__ import annotations
import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.keycloak import CATEGORY, extract


class _FakeClient:
    def __init__(self, users: object, groups: object, clients: object) -> None:
        self._users = users
        self._groups = groups
        self._clients = clients

    def list_users(self, realm: str) -> object:
        return self._users

    def list_groups(self, realm: str) -> object:
        return self._groups

    def list_clients(self, realm: str) -> object:
        return self._clients


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.14")
def test_extract_returns_user_group_and_application_entities() -> None:
    config = {
        "client": _FakeClient(
            users=[{"id": "u1", "username": "jo", "email": "jo@example.com"}],
            groups=[{"id": "g1", "name": "admins"}],
            clients=[{"id": "c1", "clientId": "web-app"}],
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 3
    user, group, application = result.entities
    assert isinstance(user, Entity)
    assert user.id == "kc_user:u1"
    assert user.node_type == "IdentityUser"
    assert user.properties["realm"] == "master"
    assert group.id == "kc_group:g1"
    assert group.node_type == "IdentityGroup"
    assert application.id == "kc_client:c1"
    assert application.node_type == "Application"
    assert application.properties["name"] == "web-app"
    assert result.relationships == ()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.14")
def test_extract_uses_the_configured_realm() -> None:
    config = {
        "client": _FakeClient(
            users=[{"id": "u1", "username": "jo"}], groups=[], clients=[]
        ),
        "realm": "tenant-a",
    }

    result = extract(config)

    assert result.entities[0].properties["realm"] == "tenant-a"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.14")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.14")
def test_extract_returns_an_empty_change_set_when_list_users_raises() -> None:
    class _BrokenClient:
        def list_users(self, realm: str) -> object:
            raise RuntimeError("down")

        def list_groups(self, realm: str) -> object:
            return []

        def list_clients(self, realm: str) -> object:
            return []

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.14")
def test_keycloak_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
