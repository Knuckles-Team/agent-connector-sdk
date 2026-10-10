"""SDK-SOURCE-INGEST-R006.17/18/19: wger, Okta, Twenty vendor extractor ports.

Also exercises the shared :mod:`agent_connector_sdk.vendor_extractors.contract`
names (``VendorExtractor``, ``VendorExtractFn``, ``register_vendor_extractor``,
``discover_vendor_extractors``) that SDK-SOURCE-INGEST-R006.1 introduced but
left untested, so ``scripts/check_wiring.py public-api`` has a real test for
each public contract name.
"""

from __future__ import annotations
import pytest

from agent_connector_sdk.ingest import ChangeSet
from agent_connector_sdk.vendor_extractors import (
    VendorExtractFn,
    VendorExtractor,
    discover_vendor_extractors,
    get_vendor_extractor,
    list_vendor_extractors,
    register_vendor_extractor,
)
from agent_connector_sdk.vendor_extractors.okta import CATEGORY as OKTA_CATEGORY
from agent_connector_sdk.vendor_extractors.okta import extract as okta_extract
from agent_connector_sdk.vendor_extractors.twenty import CATEGORY as TWENTY_CATEGORY
from agent_connector_sdk.vendor_extractors.twenty import extract as twenty_extract
from agent_connector_sdk.vendor_extractors.wger import CATEGORY as WGER_CATEGORY
from agent_connector_sdk.vendor_extractors.wger import extract as wger_extract


class _FakeClient:
    def __init__(self, **methods: object) -> None:
        self._methods = methods

    def __getattr__(self, name: str) -> object:
        if name in self._methods:
            value = self._methods[name]
            return value if callable(value) else (lambda: value)
        raise AttributeError(name)


def test_contract_registry_accepts_a_typed_vendor_extractor() -> None:
    def extract(config: object) -> ChangeSet:  # pragma: no cover - trivial
        return ChangeSet()

    fn: VendorExtractFn = extract
    register_vendor_extractor("test_contract_probe", fn, description="probe")

    registered = get_vendor_extractor("test_contract_probe")

    assert isinstance(registered, VendorExtractor)
    assert registered.extract is extract
    assert "test_contract_probe" in [v.category for v in list_vendor_extractors()]


def test_discover_vendor_extractors_imports_every_module_at_least_once() -> None:
    assert discover_vendor_extractors() >= 1


# --- wger ------------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.17")
def test_wger_extract_maps_weight_and_sessions_to_body_measurement_entities() -> None:
    client = _FakeClient(
        get_weight_entries=[{"id": 1, "weight": 80.5, "date": "2026-01-01"}],
        get_measurements=[],
        get_workout_sessions=[
            {"id": 5, "date": "2026-01-01", "impression": "good", "routine": 9}
        ],
        get_nutrition_plans=[],
    )

    result = wger_extract({"client": client})

    assert isinstance(result, ChangeSet)
    ids = {entity.id for entity in result.entities}
    assert "wger:weight:1" in ids
    assert "wger:session:5" in ids
    weight = next(e for e in result.entities if e.id == "wger:weight:1")
    assert weight.node_type == "BodyMeasurement"
    assert weight.properties["domain"] == WGER_CATEGORY
    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source == "wger:session:5"
    assert rel.target == "wger:routine:9"
    assert rel.relationship == "PART_OF"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.17")
def test_wger_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert wger_extract({}) == ChangeSet()


# --- okta --------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.18")
def test_okta_extract_links_group_members_and_maps_apps() -> None:
    client = _FakeClient(
        list_users=[{"id": "u1", "profile": {"email": "a@example.com"}}],
        list_groups=[{"id": "g1", "profile": {"name": "eng"}}],
        list_group_members=lambda group_id: [{"id": "u1"}] if group_id == "g1" else [],
        list_apps=[{"id": "app1", "label": "Okta Admin", "status": "ACTIVE"}],
    )

    result = okta_extract({"client": client})

    entity_ids = {entity.id for entity in result.entities}
    assert "okta_user:u1" in entity_ids
    assert "okta_group:g1" in entity_ids
    assert "okta_app:app1" in entity_ids
    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source == "okta_user:u1"
    assert rel.target == "okta_group:g1"
    assert rel.relationship == "MEMBER_OF_GROUP"
    app = next(e for e in result.entities if e.id == "okta_app:app1")
    assert app.properties["domain"] == OKTA_CATEGORY


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.18")
def test_okta_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert okta_extract({}) == ChangeSet()


# --- twenty --------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.19")
def test_twenty_extract_maps_companies_people_and_opportunities() -> None:
    client = _FakeClient(
        get_companies={
            "data": {"companies": {"edges": [{"node": {"id": "c1", "name": "Acme"}}]}}
        },
        get_people={
            "data": {"people": [{"id": "p1", "name": "Jane", "companyId": "c1"}]}
        },
        get_opportunities={
            "data": {
                "opportunities": [
                    {
                        "id": "o1",
                        "name": "Deal",
                        "companyId": "c1",
                        "amount": {"amountMicros": 100},
                    }
                ]
            }
        },
    )

    result = twenty_extract({"client": client})

    entity_ids = {entity.id for entity in result.entities}
    assert entity_ids == {"twcompany:c1", "twperson:p1", "twopp:o1"}
    rel_types = {
        (rel.source, rel.target, rel.relationship) for rel in result.relationships
    }
    assert ("twperson:p1", "twcompany:c1", "BELONGS_TO") in rel_types
    assert ("twopp:o1", "twcompany:c1", "PLACED_BY") in rel_types
    opp = next(e for e in result.entities if e.id == "twopp:o1")
    assert opp.properties["amount"] == 100
    assert opp.properties["domain"] == TWENTY_CATEGORY


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.19")
def test_twenty_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert twenty_extract({}) == ChangeSet()
