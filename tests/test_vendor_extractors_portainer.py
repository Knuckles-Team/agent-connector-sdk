"""SDK-SOURCE-INGEST-R006.11: the Portainer vendor extractor port."""

from __future__ import annotations

import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.portainer import CATEGORY, extract


class _FakeClient:
    def __init__(
        self,
        endpoints: object,
        containers_by_endpoint: dict[object, object],
        stacks: object,
    ) -> None:
        self._endpoints = endpoints
        self._containers_by_endpoint = containers_by_endpoint
        self._stacks = stacks

    def get_endpoints(self) -> object:
        return self._endpoints

    def list_containers(self, endpoint_id: object) -> object:
        return self._containers_by_endpoint.get(endpoint_id, [])

    def list_stacks(self) -> object:
        return self._stacks


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.11")
def test_extract_returns_server_asset_and_service_entities() -> None:
    config = {
        "client": _FakeClient(
            endpoints=[{"Id": 1, "Name": "prod"}],
            containers_by_endpoint={
                1: [
                    {
                        "Id": "c1",
                        "Names": ["/web"],
                        "Image": "nginx",
                        "State": "running",
                    }
                ]
            },
            stacks=[{"Id": 9, "Name": "monitoring"}],
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 3
    endpoint, container, stack = result.entities
    assert isinstance(endpoint, Entity)
    assert endpoint.id == "portainer_endpoint:1"
    assert endpoint.node_type == "Server"
    assert container.id == "portainer_container:1:c1"
    assert container.node_type == "AssetInstance"
    assert container.properties["name"] == "web"
    assert stack.id == "portainer_stack:9"
    assert stack.node_type == "Service"
    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert isinstance(relationship, Relationship)
    assert relationship.source == "portainer_container:1:c1"
    assert relationship.target == "portainer_endpoint:1"
    assert relationship.relationship == "RUNS_ON"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.11")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.11")
def test_extract_returns_an_empty_change_set_when_get_endpoints_raises() -> None:
    class _BrokenClient:
        def get_endpoints(self) -> object:
            raise RuntimeError("down")

        def list_stacks(self) -> object:
            return []

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.11")
def test_portainer_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
