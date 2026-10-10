"""SDK-SOURCE-INGEST-R006.26/27/28: ServiceNow, CISO Assistant, social vendor extractor ports."""

from __future__ import annotations

import pytest

from agent_connector_sdk.ingest import ChangeSet
from agent_connector_sdk.vendor_extractors.ciso_assistant import (
    CATEGORY as CISO_CATEGORY,
)
from agent_connector_sdk.vendor_extractors.ciso_assistant import (
    extract as ciso_extract,
)
from agent_connector_sdk.vendor_extractors.servicenow import (
    CATEGORY as SERVICENOW_CATEGORY,
)
from agent_connector_sdk.vendor_extractors.servicenow import (
    extract as servicenow_extract,
)
from agent_connector_sdk.vendor_extractors.social import CATEGORY as SOCIAL_CATEGORY
from agent_connector_sdk.vendor_extractors.social import extract as social_extract


class _FakeClient:
    def __init__(self, **methods: object) -> None:
        self._methods = methods

    def __getattr__(self, name: str) -> object:
        if name in self._methods:
            value = self._methods[name]
            return value if callable(value) else (lambda: value)
        raise AttributeError(name)


# --- servicenow ------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.26")
def test_servicenow_extract_links_incidents_and_emits_risk_entities() -> None:
    client = _FakeClient(
        incidents=[
            {
                "sys_id": "inc1",
                "number": "INC0001",
                "cmdb_ci": "ci1",
                "assigned_to": "u1",
            }
        ],
        changes=[],
        cmdb_cis=[{"sys_id": "ci1", "name": "web-01", "eol_date": "2027-01-01"}],
        cmdb_models=[],
        assets=[],
    )

    result = servicenow_extract({"client": client})

    assert isinstance(result, ChangeSet)
    entity_ids = {entity.id for entity in result.entities}
    assert {"incident:inc1", "ci:ci1", "snrisk:ci:ci1"} <= entity_ids
    rel_tuples = {(r.source, r.target, r.relationship) for r in result.relationships}
    assert ("incident:inc1", "ci:ci1", "AFFECTS") in rel_tuples
    assert ("incident:inc1", "person:u1", "ASSIGNED_TO") in rel_tuples
    assert ("ci:ci1", "snrisk:ci:ci1", "HAS_RISK") in rel_tuples
    ci = next(e for e in result.entities if e.id == "ci:ci1")
    assert ci.properties["domain"] == SERVICENOW_CATEGORY


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.26")
def test_servicenow_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert servicenow_extract({}) == ChangeSet()


# --- ciso_assistant ------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.27")
def test_ciso_assistant_extract_links_risk_scenarios_to_controls() -> None:
    def api_risk_scenarios_list() -> list[dict]:
        return [
            {
                "id": "risk1",
                "name": "Vendor outage",
                "applied_controls": [{"id": "ctrl1"}],
            }
        ]

    def api_applied_controls_list() -> list[dict]:
        return [{"id": "ctrl1", "name": "Vendor SLA"}]

    client = _FakeClient(
        api_risk_scenarios_list=api_risk_scenarios_list,
        api_applied_controls_list=api_applied_controls_list,
    )

    result = ciso_extract({"client": client})

    entity_ids = {entity.id for entity in result.entities}
    assert "ciso_assistant_risk:risk1" in entity_ids
    assert "ciso_assistant_control:ctrl1" in entity_ids
    rel_tuples = {(r.source, r.target, r.relationship) for r in result.relationships}
    assert (
        "ciso_assistant_risk:risk1",
        "ciso_assistant_control:ctrl1",
        "MITIGATED_BY",
    ) in rel_tuples
    risk = next(e for e in result.entities if e.id == "ciso_assistant_risk:risk1")
    assert risk.node_type == "Risk"
    assert risk.properties["domain"] == CISO_CATEGORY


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.27")
def test_ciso_assistant_extract_returns_an_empty_change_set_without_a_client() -> None:
    assert ciso_extract({}) == ChangeSet()


# --- social ------------------------------------------------------------


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.28")
def test_social_extract_mines_hashtags_mentions_and_known_tools() -> None:
    record = {
        "entities": {
            "hashtags": [{"tag": "AI"}],
            "user_mentions": [{"screen_name": "octocat"}],
            "urls": [{"expanded_url": "https://github.com/octocat/hello"}],
        }
    }

    result = social_extract({"record": record, "document_id": "doc:1"})

    assert isinstance(result, ChangeSet)
    entity_ids = {entity.id for entity in result.entities}
    assert entity_ids == {"hashtag:ai", "mention:octocat", "tool:github"}
    rel_tuples = {(r.source, r.target, r.relationship) for r in result.relationships}
    assert ("doc:1", "hashtag:ai", "taggedWithHashtag") in rel_tuples
    assert ("doc:1", "mention:octocat", "mentionsHandle") in rel_tuples
    assert ("doc:1", "tool:github", "referencesTool") in rel_tuples
    hashtag = next(e for e in result.entities if e.id == "hashtag:ai")
    assert hashtag.properties["extraction_stage"] == "deterministic"
    assert SOCIAL_CATEGORY == "social"


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.28")
def test_social_extract_reads_the_legacy_v1_1_entities_shape() -> None:
    record = {"legacy": {"entities": {"hashtags": [{"text": "News"}]}}}

    result = social_extract({"record": record, "document_id": "doc:2"})

    assert {e.id for e in result.entities} == {"hashtag:news"}


@pytest.mark.spec("SDK-SOURCE-INGEST-R006.28")
def test_social_extract_returns_an_empty_change_set_without_a_record() -> None:
    assert social_extract({}) == ChangeSet()
