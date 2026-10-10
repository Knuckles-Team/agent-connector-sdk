"""SDK-SOURCE-INGEST-R006.7: the Salesforce CRM vendor extractor port."""

from __future__ import annotations

import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.salesforce import CATEGORY, extract


class _FakeClient:
    def __init__(self, rows_by_object: dict[str, list[dict[str, object]]]) -> None:
        self._rows_by_object = rows_by_object

    def query(self, soql: str) -> object:
        for sobject, rows in self._rows_by_object.items():
            if f"FROM {sobject}" in soql:
                return {"records": rows}
        return {"records": []}


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.7")
def test_extract_returns_customer_contact_and_order_entities_with_relationships() -> (
    None
):
    config = {
        "client": _FakeClient(
            {
                "Account": [{"Id": "001", "Name": "Acme"}],
                "Contact": [{"Id": "003", "Name": "Jo", "AccountId": "001"}],
                "Opportunity": [{"Id": "006", "Name": "Deal", "AccountId": "001"}],
            }
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 3
    customer = result.entities[0]
    assert isinstance(customer, Entity)
    assert customer.id == "sfaccount:001"
    assert customer.node_type == "Customer"
    assert customer.properties["domain"] == "salesforce"
    assert len(result.relationships) == 2
    contact_rel, opp_rel = result.relationships
    assert isinstance(contact_rel, Relationship)
    assert contact_rel.source == "sfcontact:003"
    assert contact_rel.target == "sfaccount:001"
    assert contact_rel.relationship == "BELONGS_TO"
    assert opp_rel.source == "sfopp:006"
    assert opp_rel.relationship == "PLACED_BY"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.7")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.7")
def test_extract_returns_an_empty_change_set_when_query_raises() -> None:
    class _BrokenClient:
        def query(self, soql: str) -> object:
            raise RuntimeError("down")

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.7")
def test_salesforce_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
