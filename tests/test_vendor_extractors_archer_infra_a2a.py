"""SDK-SOURCE-INGEST-R006.20/21/22: Archer, Infra, A2A vendor extractor ports."""

from __future__ import annotations

import pytest
from agent_connector_sdk.ingest import ChangeSet
from agent_connector_sdk.vendor_extractors.a2a import CATEGORY as A2A_CATEGORY
from agent_connector_sdk.vendor_extractors.a2a import extract as a2a_extract
from agent_connector_sdk.vendor_extractors.archer import CATEGORY as ARCHER_CATEGORY
from agent_connector_sdk.vendor_extractors.archer import extract as archer_extract
from agent_connector_sdk.vendor_extractors.infra import CATEGORY as INFRA_CATEGORY
from agent_connector_sdk.vendor_extractors.infra import extract as infra_extract


class _FakeClient:
    def __init__(self, **methods: object) -> None:
        self._methods = methods

    def __getattr__(self, name: str) -> object:
        if name in self._methods:
            value = self._methods[name]
            return value if callable(value) else (lambda: value)
        raise AttributeError(name)


# --- archer ------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.20", "SDK-SOURCE-INGEST-R006.21", "SDK-SOURCE-INGEST-R006.22")
def test_archer_extract_links_controls_to_risks_and_findings_to_controls() -> None:
    client = _FakeClient(
        list_risks=[{"id": "r1", "name": "Data loss"}],
        list_controls=[{"id": "c1", "name": "Backups", "riskId": "r1"}],
        list_findings=[{"id": "f1", "name": "Backup gap", "controlId": "c1"}],
    )

    result = archer_extract({"client": client})

    assert isinstance(result, ChangeSet)
    entity_ids = {entity.id for entity in result.entities}
    assert entity_ids == {"archer_risk:r1", "archer_control:c1", "archer_finding:f1"}
    risk = next(e for e in result.entities if e.id == "archer_risk:r1")
    assert risk.node_type == "Risk"
    assert risk.properties["capability"] == "grc"
    rel_types = {(r.source, r.target, r.relationship) for r in result.relationships}
    assert ("archer_control:c1", "archer_risk:r1", "MITIGATES") in rel_types
    assert ("archer_finding:f1", "archer_control:c1", "AFFECTS") in rel_types
    assert ARCHER_CATEGORY == "archer"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.20", "SDK-SOURCE-INGEST-R006.21", "SDK-SOURCE-INGEST-R006.22")
def test_archer_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert archer_extract({}) == ChangeSet()


# --- infra ------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.20", "SDK-SOURCE-INGEST-R006.21")
def test_infra_extract_maps_ansible_style_inventory_and_docker_services() -> None:
    config = {
        "inventory": {
            "all": {"hosts": {"node1": {"ansible_host": "10.0.0.5", "roles": "db"}}}
        },
        "services": [{"name": "api", "image": "api:1", "replicas": 2, "node": "node1"}],
    }

    result = infra_extract(config)

    entity_ids = {entity.id for entity in result.entities}
    assert entity_ids == {"server:node1", "service:api"}
    server = next(e for e in result.entities if e.id == "server:node1")
    assert server.properties["ip"] == "10.0.0.5"
    assert server.properties["roles"] == ["db"]
    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source == "service:api"
    assert rel.target == "server:node1"
    assert rel.relationship == "RUNS_ON"
    assert INFRA_CATEGORY == "infra"


def test_infra_extract_returns_an_empty_change_set_for_an_empty_config() -> None:
    assert infra_extract({}) == ChangeSet()


# --- a2a ------------------------------------------------------------


def test_a2a_extract_maps_cards_and_skills() -> None:
    config = {
        "cards": [
            {
                "name": "Research Agent",
                "description": "Finds things",
                "url": "https://agent.example/a2a",
                "skills": [{"name": "Web Search", "tags": ["search"]}],
            }
        ]
    }

    result = a2a_extract(config)

    entity_ids = {entity.id for entity in result.entities}
    assert "a2a:research-agent" in entity_ids
    assert "skill:a2a:research-agent:web-search" in entity_ids
    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.source == "a2a:research-agent"
    assert rel.target == "skill:a2a:research-agent:web-search"
    assert rel.relationship == "EXPOSES_SKILL"
    assert A2A_CATEGORY == "a2a"


def test_a2a_extract_returns_an_empty_change_set_for_no_cards() -> None:
    assert a2a_extract({}) == ChangeSet()
