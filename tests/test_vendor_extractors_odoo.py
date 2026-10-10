"""SDK-SOURCE-INGEST-R006.15: the Odoo CRM vendor extractor port."""

from __future__ import annotations

import pytest

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors import (
    get_vendor_extractor,
    list_vendor_extractors,
)
from agent_connector_sdk.vendor_extractors.odoo import CATEGORY, extract


class _FakeClient:
    def __init__(self, partners: object, leads: object) -> None:
        self._partners = partners
        self._leads = leads

    def list_partners(self) -> object:
        return self._partners

    def list_leads(self) -> object:
        return self._leads


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.15")
def test_extract_returns_customer_and_lead_entities_with_belongs_to() -> None:
    config = {
        "client": _FakeClient(
            partners=[{"id": 1, "display_name": "Acme Corp"}],
            leads=[{"id": 9, "name": "Big Deal", "partner_id": [1, "Acme Corp"]}],
        )
    }

    result = extract(config)

    assert isinstance(result, ChangeSet)
    assert len(result.entities) == 2
    customer, lead = result.entities
    assert isinstance(customer, Entity)
    assert customer.id == "odoo_customer:1"
    assert customer.node_type == "Customer"
    assert customer.properties["capability"] == "crm"
    assert lead.id == "odoo_lead:9"
    assert lead.node_type == "Lead"
    assert len(result.relationships) == 1
    relationship = result.relationships[0]
    assert isinstance(relationship, Relationship)
    assert relationship.source == "odoo_lead:9"
    assert relationship.target == "odoo_customer:1"
    assert relationship.relationship == "BELONGS_TO"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.15")
def test_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert extract({}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.15")
def test_extract_returns_an_empty_change_set_when_list_partners_raises() -> None:
    class _BrokenClient:
        def list_partners(self) -> object:
            raise RuntimeError("down")

        def list_leads(self) -> object:
            return []

    assert extract({"client": _BrokenClient()}) == ChangeSet()


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.15")
def test_odoo_self_registers_under_the_vendor_extractor_registry() -> None:
    registered = get_vendor_extractor(CATEGORY)

    assert registered is not None
    assert registered.extract is extract
    assert CATEGORY in [vendor.category for vendor in list_vendor_extractors()]
