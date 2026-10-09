"""SDK-SOURCE-INGEST-R006.10: the Technitium DNS vendor extractor port."""

from __future__ import annotations

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.technitium_dns import CATEGORY, extract


class _FakeClient:
    def __init__(self, zones: object, records_by_zone: dict[str, object]) -> None:
        self._zones = zones
        self._records_by_zone = records_by_zone

    def list_zones(self) -> object:
        return self._zones

    def get_records(self, zone: str) -> object:
        return self._records_by_zone.get(zone, [])


def test_extract_returns_zone_and_record_entities_with_contains_relationships() -> None:
    config = {
        "client": _FakeClient(
            zones=[{"name": "example.com"}],
            records_by_zone={
                "example.com": [{"name": "www", "type": "A", "value": "10.0.0.1"}]
            },
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 2
    zone, record = result.entities
    assert isinstance(zone, Entity)
    assert zone.id == "dnszone:example.com"
    assert zone.node_type == "ConfigurationItem"
    assert zone.properties["ci_class"] == "dns_zone"
    assert record.id == "dnsrecord:example.com:www:A"
    assert record.properties["ci_class"] == "dns_a"
    assert record.properties["value"] == "10.0.0.1"
    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert isinstance(relationship, Relationship)
    assert relationship.source == "dnszone:example.com"
    assert relationship.target == "dnsrecord:example.com:www:A"
    assert relationship.relationship == "CONTAINS"


def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


def test_extract_returns_an_empty_change_set_when_list_zones_raises() -> None:
    class _BrokenClient:
        def list_zones(self) -> object:
            raise RuntimeError("down")

        def get_records(self, zone: str) -> object:
            return []

    assert extract({"client": _BrokenClient()}) == ChangeSet()


def test_technitium_dns_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
