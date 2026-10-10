"""SDK-SOURCE-INGEST-R006.23/24/25: Grafana, LeanIX, ERPNext vendor extractor ports."""

from __future__ import annotations

import pytest

from agent_connector_sdk.ingest import ChangeSet
from agent_connector_sdk.vendor_extractors.erpnext import CATEGORY as ERPNEXT_CATEGORY
from agent_connector_sdk.vendor_extractors.erpnext import extract as erpnext_extract
from agent_connector_sdk.vendor_extractors.grafana import CATEGORY as GRAFANA_CATEGORY
from agent_connector_sdk.vendor_extractors.grafana import extract as grafana_extract
from agent_connector_sdk.vendor_extractors.leanix import CATEGORY as LEANIX_CATEGORY
from agent_connector_sdk.vendor_extractors.leanix import extract as leanix_extract


class _FakeClient:
    def __init__(self, **methods: object) -> None:
        self._methods = methods

    def __getattr__(self, name: str) -> object:
        if name in self._methods:
            value = self._methods[name]
            return value if callable(value) else (lambda: value)
        raise AttributeError(name)


# --- grafana ------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.23")
def test_grafana_extract_links_panels_to_dashboards_and_monitored_services() -> None:
    client = _FakeClient(
        datasources=[{"uid": "ds1", "name": "Prometheus", "type": "prometheus"}],
        dashboards=[
            {
                "uid": "d1",
                "title": "API",
                "panels": [
                    {
                        "id": 1,
                        "title": "errors",
                        "targets": [],
                        "labels": {"service": "api"},
                    }
                ],
            }
        ],
        alert_rules=[{"uid": "a1", "title": "High CPU: service=api"}],
    )

    result = grafana_extract({"client": client})

    assert isinstance(result, ChangeSet)
    entity_ids = {entity.id for entity in result.entities}
    assert {"datasource:ds1", "dashboard:d1", "panel:d1:1", "alert:a1"} <= entity_ids
    rel_tuples = {(r.source, r.target, r.relationship) for r in result.relationships}
    assert ("panel:d1:1", "dashboard:d1", "PART_OF") in rel_tuples
    assert ("panel:d1:1", "service:api", "MONITORS") in rel_tuples
    assert ("alert:a1", "service:api", "MONITORS") in rel_tuples
    assert GRAFANA_CATEGORY == "grafana"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.23")
def test_grafana_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert grafana_extract({}) == ChangeSet()


# --- leanix ------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.24")
def test_leanix_extract_maps_factsheets_and_known_relations() -> None:
    def factsheets(type: str, since: object = None, ids: object = None) -> list[dict]:
        if type == "Application":
            return [
                {
                    "id": "app-1",
                    "name": "Billing",
                    "relApplicationToBusinessCapability": {"id": "cap-1"},
                }
            ]
        if type == "BusinessCapability":
            return [{"id": "cap-1", "name": "Finance"}]
        return []

    client = _FakeClient(factsheets=factsheets)

    result = leanix_extract({"client": client})

    entity_ids = {entity.id for entity in result.entities}
    assert entity_ids == {"app:app-1", "capability:cap-1"}
    app = next(e for e in result.entities if e.id == "app:app-1")
    assert app.node_type == "Application"
    assert app.properties["domain"] == "leanix"
    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source == "app:app-1"
    assert rel.target == "capability:cap-1"
    assert rel.relationship == "SUPPORTS"
    assert LEANIX_CATEGORY == "leanix"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.24")
def test_leanix_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert leanix_extract({}) == ChangeSet()


# --- erpnext ------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.25")
def test_erpnext_extract_maps_doctypes_and_relationships() -> None:
    def get_list(doctype: str) -> list[dict]:
        return {
            "Employee": [
                {"name": "EMP-1", "employee_name": "Jane", "department": "Eng"}
            ],
            "Customer": [{"name": "CUST-1", "customer_name": "Acme"}],
            "Sales Order": [{"name": "SO-1", "customer": "CUST-1", "grand_total": 500}],
            "Item": [{"name": "ITEM-1", "item_name": "Widget"}],
            "Asset": [{"name": "AST-1", "item_code": "ITEM-1", "warehouse": "WH-1"}],
            "Warehouse": [{"name": "WH-1"}],
            "Issue": [{"name": "ISS-1", "customer": "CUST-1", "subject": "Broken"}],
        }.get(doctype, [])

    client = _FakeClient(get_list=get_list)

    result = erpnext_extract({"client": client})

    entity_ids = {entity.id for entity in result.entities}
    assert entity_ids == {
        "employee:EMP-1",
        "orgunit:Eng",
        "customer:CUST-1",
        "order:SO-1",
        "item:ITEM-1",
        "asset:AST-1",
        "warehouse:WH-1",
        "erpnextissue:ISS-1",
    }
    rel_tuples = {(r.source, r.target, r.relationship) for r in result.relationships}
    assert ("employee:EMP-1", "orgunit:Eng", "MEMBER_OF") in rel_tuples
    assert ("order:SO-1", "customer:CUST-1", "PLACED_BY") in rel_tuples
    assert ("asset:AST-1", "item:ITEM-1", "INSTANCE_OF") in rel_tuples
    assert ("asset:AST-1", "warehouse:WH-1", "LOCATED_IN") in rel_tuples
    assert ("erpnextissue:ISS-1", "customer:CUST-1", "RAISED_BY") in rel_tuples
    employee = next(e for e in result.entities if e.id == "employee:EMP-1")
    assert employee.properties["domain"] == ERPNEXT_CATEGORY
    assert employee.properties["externalToolId"] == "EMP-1"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.25")
def test_erpnext_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert erpnext_extract({}) == ChangeSet()
