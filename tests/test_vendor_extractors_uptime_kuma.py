"""SDK-SOURCE-INGEST-R006.1: the typed vendor-extractor contract + Uptime Kuma port."""

from __future__ import annotations

import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.uptime_kuma import CATEGORY, extract


class _FakeClient:
    def __init__(self, monitors: object) -> None:
        self._monitors = monitors

    def get_monitors(self) -> object:
        return self._monitors


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.1")
def test_extract_returns_a_change_set_of_entities_for_dict_shaped_monitors() -> None:
    config = {
        "client": _FakeClient(
            {
                1: {
                    "id": 1,
                    "name": "api",
                    "url": "https://api.example",
                    "active": True,
                },
            }
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 1
    entity = result.entities[0]
    assert isinstance(entity, Entity)
    assert entity.id == "uptime_monitor:1"
    assert entity.node_type == "Service"
    assert entity.properties["name"] == "api"
    assert entity.properties["url"] == "https://api.example"
    assert entity.properties["externalToolId"] == "1"
    assert entity.properties["domain"] == "uptime_kuma"
    assert result.relationships == ()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.1")
def test_extract_accepts_list_shaped_monitors_and_skips_unidentified_ones() -> None:
    config = {"client": _FakeClient([{"name": "db"}, {"url": "https://no-id.example"}])}

    result = extract(config)

    assert len(result.entities) == 1
    assert result.entities[0].id == "uptime_monitor:db"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.1")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.1")
def test_extract_returns_an_empty_change_set_when_get_monitors_raises() -> None:
    class _BrokenClient:
        def get_monitors(self) -> object:
            raise RuntimeError("down")

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.1")
def test_uptime_kuma_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
