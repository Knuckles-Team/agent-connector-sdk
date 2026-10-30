"""Camunda BPMN vendor extractor (SCION-SOURCE-INGEST-R006.31).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.camunda``
onto this SDK's typed :mod:`~scion_sdk.vendor_extractors.contract`:
process definitions, tasks, and incidents map to the canonical ArchiMate
concepts, so Camunda data folds into the same cross-vendor crosswalk as
ServiceNow/ERPNext/ARIS:

    process definition -> ``BusinessProcess``   id=bpmn_process:{id}
    task               -> ``BusinessTask``      id=bpmn_task:{id}   (PART_OF process)
    incident           -> ``Incident``          id=incident:{id}    (AFFECTS process)

A process definition carrying an Egeria GUID gets the ``externalToolId``
federation-key property plus an ``ALIGNED_WITH`` equivalence relationship to
its ``egeria_process:{guid}`` twin -- exactly how the egeria extractor stores
external ids. The Camunda client is injected (duck-typed) via
``config["client"]``, expected to expose the camunda-mcp surface
(``list_process_definitions()``, ``list_tasks()``, ``list_incidents()``).
This module performs no network calls itself.

Scope note: the agent-utilities source additionally lifts each definition's
static BPMN 2.0 XML structure (tasks/gateways -> ``BusinessTask``/
``FLOWS_TO``) when the client also serves ``get_process_definition_xml``, via
a graph-collapse algorithm shared with the ARIS extractor. This port carries
over the process/task/incident-level mapping and crosswalk only; the
step-level BPMN XML lift is not ported in this change (follow-up).
"""

from __future__ import annotations

from typing import Any

from scion_sdk.ingest import ChangeSet, Entity, Relationship
from scion_sdk.vendor_extractors import _records as rec
from scion_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "camunda"


def _call(client: Any, name: str) -> list[Any]:
    """Call a client list-method if present, returning a list (tolerant)."""
    return rec._call_list(client, name, ("items", "results"))


def _extract_processes(
    client: Any, entities: list[Entity], relationships: list[Relationship]
) -> None:
    """Append process-definition entities (and Egeria alignment links)."""
    for record in _call(client, "list_process_definitions"):
        proc_id = rec._first(record, "id", "key", "bpmnProcessId")
        if not proc_id:
            continue
        proc_node_id = f"bpmn_process:{proc_id}"
        properties: dict[str, Any] = {
            "name": rec._first(record, "name", "key", "bpmnProcessId"),
            "key": rec._first(record, "key", "bpmnProcessId"),
            "version": rec._get(record, "version"),
        }
        egeria_guid = rec._first(record, "egeriaGuid", "egeria_guid", "externalToolId")
        if egeria_guid:
            properties["externalToolId"] = egeria_guid
            relationships.append(
                Relationship(
                    source=proc_node_id,
                    target=f"egeria_process:{egeria_guid}",
                    relationship="ALIGNED_WITH",
                )
            )
        entities.append(
            Entity(id=proc_node_id, node_type="BusinessProcess", properties=properties)
        )


def _present(pairs: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    """Return ``pairs`` as a dict, dropping ``None`` values."""
    return {key: value for key, value in pairs if value is not None}


def _extract_tasks(
    client: Any, entities: list[Entity], relationships: list[Relationship]
) -> None:
    """Append task entities linked ``PART_OF`` their process."""
    for record in _call(client, "list_tasks"):
        task_id = rec._first(record, "id", "key")
        if not task_id:
            continue
        node_id = f"bpmn_task:{task_id}"
        properties = _present(
            (
                ("name", rec._first(record, "name", "taskDefinitionKey")),
                ("assignee", rec._get(record, "assignee")),
            )
        )
        entities.append(
            Entity(id=node_id, node_type="BusinessTask", properties=properties)
        )
        _link_process(
            record, node_id, relationship="PART_OF", relationships=relationships
        )


def _link_process(
    record: Any,
    node_id: str,
    *,
    relationship: str,
    relationships: list[Relationship],
) -> None:
    """Append a link from ``node_id`` to the record's process, if any."""
    proc_ref = rec._first(record, "processDefinitionId", "processDefinitionKey")
    if proc_ref:
        relationships.append(
            Relationship(
                source=node_id,
                target=f"bpmn_process:{proc_ref}",
                relationship=relationship,
            )
        )


def _extract_incidents(
    client: Any, entities: list[Entity], relationships: list[Relationship]
) -> None:
    """Append incident entities linked ``AFFECTS`` their process."""
    for record in _call(client, "list_incidents"):
        incident_id = rec._first(record, "id", "key")
        if not incident_id:
            continue
        node_id = f"incident:{incident_id}"
        properties = _present(
            (
                (
                    "short_description",
                    rec._first(record, "incidentMessage", "errorMessage"),
                ),
                ("incident_type", rec._get(record, "incidentType")),
            )
        )
        entities.append(Entity(id=node_id, node_type="Incident", properties=properties))
        _link_process(
            record, node_id, relationship="AFFECTS", relationships=relationships
        )


def extract(config: Any) -> ChangeSet:
    """Extract Camunda BPMN artifacts into a uniform ``ChangeSet``.

    Process definitions become ``BusinessProcess`` entities; tasks become
    ``BusinessTask`` entities linked ``PART_OF`` their process; incidents
    become ``Incident`` entities linked ``AFFECTS`` their process.
    """
    client = rec._get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    _extract_processes(client, entities, relationships)
    _extract_tasks(client, entities, relationships)
    _extract_incidents(client, entities, relationships)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Camunda BPMN (process definitions/tasks/incidents + Egeria crosswalk) -> KG",
)
