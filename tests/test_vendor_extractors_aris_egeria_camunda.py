"""SDK-SOURCE-INGEST-R006.29/30/31: ARIS, Egeria, Camunda vendor extractor ports."""

from __future__ import annotations
import pytest

from agent_connector_sdk.ingest import ChangeSet
from agent_connector_sdk.vendor_extractors.aris import CATEGORY as ARIS_CATEGORY
from agent_connector_sdk.vendor_extractors.aris import extract as aris_extract
from agent_connector_sdk.vendor_extractors.camunda import CATEGORY as CAMUNDA_CATEGORY
from agent_connector_sdk.vendor_extractors.camunda import extract as camunda_extract
from agent_connector_sdk.vendor_extractors.egeria import CATEGORY as EGERIA_CATEGORY
from agent_connector_sdk.vendor_extractors.egeria import extract as egeria_extract


class _FakeClient:
    def __init__(self, **methods: object) -> None:
        self._methods = methods

    def __getattr__(self, name: str) -> object:
        if name in self._methods:
            value = self._methods[name]
            return value if callable(value) else (lambda: value)
        raise AttributeError(name)


# --- aris ------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.29")
def test_aris_extract_distinguishes_process_and_architecture_models() -> None:
    client = _FakeClient(
        list_models=[
            {"id": "m1", "type": "EPC Process", "camundaKey": "proc-1"},
            {"id": "m2", "type": "Application Architecture"},
        ]
    )

    result = aris_extract({"client": client})

    assert isinstance(result, ChangeSet)
    process = next(e for e in result.entities if e.id == "aris_model:m1")
    architecture = next(e for e in result.entities if e.id == "aris_model:m2")
    assert process.node_type == "BusinessProcess"
    assert architecture.node_type == "ApplicationComponent"
    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source == "aris_model:m1"
    assert rel.target == "bpmn_process:proc-1"
    assert rel.relationship == "ALIGNED_WITH"
    assert ARIS_CATEGORY == "aris"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.29")
def test_aris_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert aris_extract({}) == ChangeSet()


# --- egeria ------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.30")
def test_egeria_extract_links_lineage_data_flows_through_a_process() -> None:
    client = _FakeClient(
        list_assets=[{"guid": "a1", "typeName": "RelationalTable", "name": "orders"}],
        list_glossary_categories=[],
        list_glossary_terms=[],
        list_governance_definitions=[],
        list_software_servers=[],
        list_connections=[],
        list_data_flows=[
            {
                "processGuid": "p1",
                "processName": "ETL",
                "sourceGuid": "a1",
                "targetGuid": "a2",
            }
        ],
    )

    result = egeria_extract({"client": client})

    entity_ids = {entity.id for entity in result.entities}
    assert {"egeria_asset:a1", "egeria_process:p1"} <= entity_ids
    rel_tuples = {(r.source, r.target, r.relationship) for r in result.relationships}
    assert ("egeria_asset:a1", "egeria_process:p1", "flowsTo") in rel_tuples
    assert ("egeria_process:p1", "egeria_asset:a2", "derivesFrom") in rel_tuples
    asset = next(e for e in result.entities if e.id == "egeria_asset:a1")
    assert asset.node_type == "DataObject"
    assert asset.properties["domain"] == EGERIA_CATEGORY


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.30")
def test_egeria_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert egeria_extract({}) == ChangeSet()


# --- camunda ------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.31")
def test_camunda_extract_links_tasks_and_incidents_to_their_process() -> None:
    client = _FakeClient(
        list_process_definitions=[
            {"id": "proc1", "name": "Onboarding", "egeriaGuid": "guid1"}
        ],
        list_tasks=[{"id": "task1", "processDefinitionId": "proc1"}],
        list_incidents=[{"id": "inc1", "processDefinitionId": "proc1"}],
    )

    result = camunda_extract({"client": client})

    entity_ids = {entity.id for entity in result.entities}
    assert entity_ids == {"bpmn_process:proc1", "bpmn_task:task1", "incident:inc1"}
    rel_tuples = {(r.source, r.target, r.relationship) for r in result.relationships}
    assert ("bpmn_process:proc1", "egeria_process:guid1", "ALIGNED_WITH") in rel_tuples
    assert ("bpmn_task:task1", "bpmn_process:proc1", "PART_OF") in rel_tuples
    assert ("incident:inc1", "bpmn_process:proc1", "AFFECTS") in rel_tuples
    assert CAMUNDA_CATEGORY == "camunda"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.31")
def test_camunda_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert camunda_extract({}) == ChangeSet()
