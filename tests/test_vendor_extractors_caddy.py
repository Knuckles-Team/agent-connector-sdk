"""SDK-SOURCE-INGEST-R006.3: the Caddy reverse-proxy vendor extractor port."""

from __future__ import annotations

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.caddy import CATEGORY, extract

_CONFIG = {
    "apps": {
        "http": {
            "servers": {
                "srv0": {
                    "routes": [
                        {"match": [{"host": ["api.example"]}]},
                        {"match": []},
                    ]
                }
            }
        }
    }
}


class _FakeClient:
    def __init__(self, config: object) -> None:
        self._config = config

    def get_config(self, path: str) -> object:
        return self._config


def test_extract_returns_a_change_set_of_service_entities() -> None:
    result = extract({"client": _FakeClient(_CONFIG)})

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 2
    first = result.entities[0]
    assert isinstance(first, Entity)
    assert first.id == "caddy_route:srv0:api.example"
    assert first.node_type == "Service"
    assert first.properties["hosts"] == "api.example"
    assert first.properties["server"] == "srv0"
    assert first.properties["domain"] == "caddy"
    second = result.entities[1]
    assert second.id == "caddy_route:srv0:srv0-route-1"
    assert result.relationships == ()


def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


def test_extract_returns_an_empty_change_set_when_config_is_not_a_dict() -> None:
    assert extract({"client": _FakeClient(None)}) == ChangeSet()


def test_extract_returns_an_empty_change_set_when_get_config_raises() -> None:
    class _BrokenClient:
        def get_config(self, path: str) -> object:
            raise RuntimeError("down")

    assert extract({"client": _BrokenClient()}) == ChangeSet()


def test_caddy_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
