"""SDK-SOURCE-INGEST-R006.5: the ArchiMate model vendor extractor port."""

from __future__ import annotations
import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.archimate import CATEGORY, extract


class _FakeClient:
    def __init__(self, elements: object, relationships: object) -> None:
        self._elements = elements
        self._relationships = relationships

    def list_elements(self) -> object:
        return self._elements

    def list_relationships(self) -> object:
        return self._relationships


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.5")
def test_extract_returns_typed_elements_and_relationships() -> None:
    config = {
        "client": _FakeClient(
            elements=[
                {"id": "a1", "type": "ApplicationComponent", "name": "Billing"},
            ],
            relationships=[
                {"source": "a1", "target": "a2", "type": "relServingRelationship"},
            ],
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 1
    entity = result.entities[0]
    assert isinstance(entity, Entity)
    assert entity.id == "archi:a1"
    assert entity.node_type == "ApplicationComponent"
    assert entity.properties["domain"] == "archimate"
    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert isinstance(relationship, Relationship)
    assert relationship.source == "archi:a1"
    assert relationship.target == "archi:a2"
    assert relationship.relationship == "REL_SERVING_RELATIONSHIP"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.5")
def test_extract_skips_elements_and_relationships_missing_required_fields() -> None:
    config = {
        "client": _FakeClient(
            elements=[{"id": "a1"}],
            relationships=[{"source": "a1"}],
        )
    }

    result = extract(config)

    assert result.entities == ()
    assert result.relationships == ()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.5")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.5")
def test_extract_returns_an_empty_change_set_when_list_elements_raises() -> None:
    class _BrokenClient:
        def list_elements(self) -> object:
            raise RuntimeError("down")

        def list_relationships(self) -> object:
            return []

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.5")
def test_archimate_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
