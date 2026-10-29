"""Declared source edges: owner, steward and assignment references (SCION-SOURCE-INGEST-R004.36)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_connector_sdk.ingest.live_declaration import source_meta
from agent_connector_sdk.ingest.model import EntityRef, IngestBinding
from agent_connector_sdk.ingest.request import build_request
from agent_connector_sdk.ingest.sources import EdgeSpec, IngestSourceSpec
from tests.test_source_sync import _Checkpoints, _Ingest, _runner, _Session

INCIDENTS = [
    {
        "sys_id": "inc-1",
        "short_description": "db01 down",
        "assignment_group": {"value": "grp-db", "display_value": "Database Ops"},
        "assigned_to": {"value": "usr-ann", "display_value": "Ann"},
        "watch_list": [{"value": "usr-bob"}, {"value": "usr-ann"}],
        "sys_updated_on": "2026-10-01",
    },
    {
        "sys_id": "inc-2",
        "short_description": "unassigned",
        "assignment_group": "",
        "assigned_to": "usr-cat",
        "watch_list": [],
        "sys_updated_on": "2026-10-02",
    },
]

EDGES = (
    {
        "relationship": "assignedToGroup",
        "target_field": "assignment_group",
        "target_type": "AssignmentGroup",
        "target_id_key": "value",
        "target_fields": {"name": "display_value"},
    },
    {
        "relationship": "assignedTo",
        "target_field": "assigned_to",
        "target_type": "Person",
        "target_id_key": "value",
        "target_fields": {"name": "display_value"},
    },
    {
        "relationship": "watchedBy",
        "target_field": "watch_list",
        "target_type": "Person",
        "target_id_key": "value",
    },
)


def _spec(edges: Any = EDGES) -> IngestSourceSpec:
    return IngestSourceSpec.model_validate(
        {
            "source_id": "incidents",
            "record_type": "Incident",
            "tools": ("servicenow_get_incidents",),
            "records_path": "data",
            "id_field": "sys_id",
            "cursor_field": "sys_updated_on",
            "edges": edges,
        }
    )


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.36")
def test_source_meta_declares_edges_and_refuses_bad_ones() -> None:
    meta = source_meta(
        source_id="incidents",
        record_type="Incident",
        id_field="sys_id",
        tool="servicenow_get_incidents",
        edges=list(EDGES[:1]),
    )
    (entry,) = meta["connector_sources"]
    assert entry["edges"][0]["relationship"] == "assignedToGroup"
    assert _spec().edges[0] == EdgeSpec.model_validate(EDGES[0])
    with pytest.raises(ValidationError):
        _spec([{**EDGES[0], "relationship": "has space"}])
    with pytest.raises(ValidationError):
        _spec([{**EDGES[0], "target_id_template": "group"}])
    with pytest.raises(ValidationError):
        _spec([{**EDGES[0], "unknown": 1}])


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.36")
async def test_runner_emits_reference_targets_and_relationships() -> None:
    session, ingest, checkpoints = _Session(INCIDENTS), _Ingest(), _Checkpoints()
    report = await _runner(session, ingest, checkpoints).sync(_spec(), mode="full")
    assert report.state == "completed" and report.submitted == 2
    (_binding, changes) = ingest.batches[0]
    by_id = {entity.id: entity for entity in changes.entities}
    # Records first, then each referenced target once.
    assert [e.id for e in changes.entities[:2]] == ["inc-1", "inc-2"]
    assert by_id["AssignmentGroup:grp-db"].node_type == "AssignmentGroup"
    assert by_id["AssignmentGroup:grp-db"].properties == {"name": "Database Ops"}
    assert by_id["Person:usr-ann"].properties == {"name": "Ann"}
    assert by_id["Person:usr-bob"].properties == {}
    # A scalar reference (sysparm_exclude_reference_link) is the id itself.
    assert by_id["Person:usr-cat"].properties == {}
    edges = {(r.source.id, r.relationship, r.target) for r in changes.relationships}
    assert edges == {
        ("inc-1", "assignedToGroup", "AssignmentGroup:grp-db"),
        ("inc-1", "assignedTo", "Person:usr-ann"),
        ("inc-1", "watchedBy", "Person:usr-bob"),
        ("inc-1", "watchedBy", "Person:usr-ann"),
        ("inc-2", "assignedTo", "Person:usr-cat"),
    }
    assert all(
        isinstance(r.source, EntityRef) and r.source.node_type == "Incident"
        for r in changes.relationships
    )
    # The record digest covers its references: an unchanged record re-sends nothing.
    again = await _runner(session, ingest, checkpoints).sync(_spec())
    assert again.submitted == 0 and len(ingest.batches) == 1


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.36")
async def test_scalar_and_dotted_references_and_the_wire_reference() -> None:
    records = [
        {"sys_id": "ci-1", "owned_by": "usr-ann", "sys_updated_on": "1"},
        {"sys_id": "ci-2", "owner": {"id": 7, "name": "Cat"}, "sys_updated_on": "2"},
    ]
    spec = IngestSourceSpec.model_validate(
        {
            "source_id": "cmdb-cis",
            "record_type": "ConfigurationItem",
            "tools": ("servicenow_get_table",),
            "records_path": "data",
            "id_field": "sys_id",
            "edges": [
                {
                    "relationship": "ownedBy",
                    "target_field": "owned_by",
                    "target_type": "Person",
                },
                {
                    "relationship": "ownedBy",
                    "target_field": "owner.id",
                    "target_type": "Person",
                    "target_id_template": "user/{id}",
                },
            ],
        }
    )
    session, ingest, checkpoints = _Session(records), _Ingest(), _Checkpoints()
    await _runner(session, ingest, checkpoints).sync(spec, mode="full")
    (_binding, changes) = ingest.batches[0]
    assert {(r.source.id, r.target) for r in changes.relationships} == {
        ("ci-1", "Person:usr-ann"),
        ("ci-2", "user/7"),
    }
    binding = IngestBinding(
        connector="servicenow-mcp",
        stream="cmdb-cis",
        server="servicenow-mcp",
        tool="servicenow_get_table",
    )
    request = build_request(binding, changes, previous=None)
    references = {r.relation_reference for r in request.relationships}
    assert references == {
        "connector:servicenow-mcp#relations/ConfigurationItem/ownedBy"
    }
    assert all(
        r.provenance.tool == "servicenow_get_table" for r in request.relationships
    )


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.36")
async def test_target_stream_names_the_other_sources_record_without_a_stub() -> None:
    records = [{"sys_id": "rel-1", "parent": "ci-app", "child": "ci-db"}]
    spec = IngestSourceSpec.model_validate(
        {
            "source_id": "cmdb-ci-relationships",
            "record_type": "CIRelationship",
            "tools": ("servicenow_get_table",),
            "records_path": "data",
            "id_field": "sys_id",
            "edges": [
                {
                    "relationship": "relationshipParent",
                    "target_field": "parent",
                    "target_type": "ConfigurationItem",
                    "target_id_template": "{id}",
                    "target_stream": "cmdb-cis",
                }
            ],
        }
    )
    session, ingest, checkpoints = _Session(records), _Ingest(), _Checkpoints()
    await _runner(session, ingest, checkpoints).sync(spec, mode="full")
    (_binding, changes) = ingest.batches[0]
    assert [e.id for e in changes.entities] == ["rel-1"]
    (edge,) = changes.relationships
    assert edge.target == EntityRef(id="ci-app", stream="cmdb-cis")
