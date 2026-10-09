"""Camunda BPMN vendor extractor (SDK-SOURCE-INGEST-R006.31).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.camunda``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
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

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "camunda"


def _get(record: Any, key: str, default: Any = None) -> Any:
    """Tolerant field access for dict records (or attr-style objects)."""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _first(record: Any, *keys: str) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        value = _get(record, key)
        if value is not None and value != "":
            return value
    return None


def _call_result(method: Any) -> Any:
    """Invoke a duck-typed accessor method, tolerating a required-arg form."""
    for call in (lambda: method(), lambda: method({})):
        try:
            return call()
        except TypeError:
            continue
        except Exception:
            return None
    return None


def _call(client: Any, name: str) -> list[Any]:
    """Call a client method if present, returning a list (tolerant).

    camunda-mcp list methods accept an optional ``params`` dict; calling with
    no arguments returns the unfiltered collection.
    """
    method = getattr(client, name, None)
    if not callable(method):
        return []
    result = _call_result(method)
    if result is None:
        return []
    if isinstance(result, dict):
        result = result.get("items") or result.get("results") or []
    return list(result) if result else []


def _process_definition_items(
    client: Any,
) -> tuple[list[Entity], list[Relationship]]:
    """Build ``BusinessProcess`` entities and their Egeria crosswalk links."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for record in _call(client, "list_process_definitions"):
        proc_id = _first(record, "id", "key", "bpmnProcessId")
        if not proc_id:
            continue
        proc_node_id = f"bpmn_process:{proc_id}"
        properties: dict[str, Any] = {
            "name": _first(record, "name", "key", "bpmnProcessId"),
            "key": _first(record, "key", "bpmnProcessId"),
            "version": _get(record, "version"),
        }
        egeria_guid = _first(record, "egeriaGuid", "egeria_guid", "externalToolId")
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
    return entities, relationships


def _task_items(client: Any) -> tuple[list[Entity], list[Relationship]]:
    """Build ``BusinessTask`` entities and their ``PART_OF`` process links."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for record in _call(client, "list_tasks"):
        task_id = _first(record, "id", "key")
        if not task_id:
            continue
        node_id = f"bpmn_task:{task_id}"
        entities.append(
            Entity(
                id=node_id,
                node_type="BusinessTask",
                properties={
                    key: value
                    for key, value in (
                        ("name", _first(record, "name", "taskDefinitionKey")),
                        ("assignee", _get(record, "assignee")),
                    )
                    if value is not None
                },
            )
        )
        proc_ref = _first(record, "processDefinitionId", "processDefinitionKey")
        if proc_ref:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"bpmn_process:{proc_ref}",
                    relationship="PART_OF",
                )
            )
    return entities, relationships


def _incident_items(client: Any) -> tuple[list[Entity], list[Relationship]]:
    """Build ``Incident`` entities and their ``AFFECTS`` process links."""
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for record in _call(client, "list_incidents"):
        incident_id = _first(record, "id", "key")
        if not incident_id:
            continue
        node_id = f"incident:{incident_id}"
        entities.append(
            Entity(
                id=node_id,
                node_type="Incident",
                properties={
                    key: value
                    for key, value in (
                        (
                            "short_description",
                            _first(record, "incidentMessage", "errorMessage"),
                        ),
                        ("incident_type", _get(record, "incidentType")),
                    )
                    if value is not None
                },
            )
        )
        proc_ref = _first(record, "processDefinitionId", "processDefinitionKey")
        if proc_ref:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"bpmn_process:{proc_ref}",
                    relationship="AFFECTS",
                )
            )
    return entities, relationships


def extract(config: Any) -> ChangeSet:
    """Extract Camunda BPMN artifacts into a uniform ``ChangeSet``.

    Process definitions become ``BusinessProcess`` entities; tasks become
    ``BusinessTask`` entities linked ``PART_OF`` their process; incidents
    become ``Incident`` entities linked ``AFFECTS`` their process.
    """
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    for builder in (_process_definition_items, _task_items, _incident_items):
        section_entities, section_relationships = builder(client)
        entities.extend(section_entities)
        relationships.extend(section_relationships)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Camunda BPMN (process definitions/tasks/incidents + Egeria crosswalk) -> KG",
)
