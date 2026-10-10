"""SDK-SOURCE-INGEST-R006.4: the Home Assistant vendor extractor port."""

from __future__ import annotations
import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.home_assistant import CATEGORY, extract


class _FakeClient:
    def __init__(self, states: object) -> None:
        self._states = states

    def get_states(self) -> object:
        return self._states


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.4")
def test_extract_returns_a_change_set_of_configuration_item_entities() -> None:
    config = {
        "client": _FakeClient(
            [
                {
                    "entity_id": "light.kitchen",
                    "state": "on",
                    "attributes": {"friendly_name": "Kitchen Light"},
                }
            ]
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 1
    entity = result.entities[0]
    assert isinstance(entity, Entity)
    assert entity.id == "ha:light.kitchen"
    assert entity.node_type == "ConfigurationItem"
    assert entity.properties["name"] == "Kitchen Light"
    assert entity.properties["state"] == "on"
    assert entity.properties["ci_class"] == "light"
    assert entity.properties["externalToolId"] == "light.kitchen"
    assert entity.properties["domain"] == "homeassistant"
    assert result.relationships == ()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.4")
def test_extract_skips_states_without_an_entity_id() -> None:
    config = {"client": _FakeClient([{"state": "on"}])}

    assert extract(config).entities == ()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.4")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.4")
def test_extract_returns_an_empty_change_set_when_get_states_raises() -> None:
    class _BrokenClient:
        def get_states(self) -> object:
            raise RuntimeError("down")

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.4")
def test_home_assistant_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
