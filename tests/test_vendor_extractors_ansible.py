"""SDK-SOURCE-INGEST-R006.2: the Ansible Tower/AWX vendor extractor port."""

from __future__ import annotations

import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.ansible import CATEGORY, extract


class _FakeClient:
    def __init__(self, hosts: object) -> None:
        self._hosts = hosts

    def list_hosts(self) -> object:
        return self._hosts


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.2")
def test_extract_returns_a_change_set_of_server_entities() -> None:
    config = {
        "client": _FakeClient(
            [{"id": 7, "name": "db01", "enabled": True}],
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 1
    entity = result.entities[0]
    assert isinstance(entity, Entity)
    assert entity.id == "ansible_host:7"
    assert entity.node_type == "Server"
    assert entity.properties["name"] == "db01"
    assert entity.properties["enabled"] is True
    assert entity.properties["externalToolId"] == "7"
    assert entity.properties["domain"] == "ansible"
    assert result.relationships == ()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.2")
def test_extract_skips_hosts_missing_a_name() -> None:
    config = {"client": _FakeClient([{"id": 1}])}

    result = extract(config)

    assert result.entities == ()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.2")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.2")
def test_extract_returns_an_empty_change_set_when_list_hosts_raises() -> None:
    class _BrokenClient:
        def list_hosts(self) -> object:
            raise RuntimeError("down")

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.2")
def test_ansible_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
