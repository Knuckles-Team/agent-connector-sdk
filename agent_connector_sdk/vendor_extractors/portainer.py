"""Portainer vendor extractor (SDK-SOURCE-INGEST-R006.11).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.portainer``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
endpoints become ``Server`` entities, stacks become ``Service`` entities, and
containers become ``AssetInstance`` entities with a ``RUNS_ON`` relationship
to their endpoint, instead of agent-utilities' ``GraphNode``/
``EnrichmentEdge``. The client is injected through ``config`` and this module
performs no I/O of its own.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors._records import _get, _safe_call
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "portainer"


def _rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        result = result.get("data") or result.get("value") or []
    return (
        [row for row in result if isinstance(row, dict)]
        if isinstance(result, list)
        else []
    )


def _endpoint_entity(endpoint_id: Any, endpoint: dict[str, Any]) -> Entity:
    return Entity(
        id=f"portainer_endpoint:{endpoint_id}",
        node_type="Server",
        properties={
            "name": endpoint.get("Name")
            or endpoint.get("name")
            or f"endpoint-{endpoint_id}",
            "externalToolId": str(endpoint_id),
            "domain": CATEGORY,
        },
    )


def _container_name(container: dict[str, Any]) -> Any:
    names = container.get("Names") or [container.get("name")]
    if isinstance(names, list) and names:
        return names[0]
    return container.get("Id") or "container"


def _container_entity(
    endpoint_id: Any, container: dict[str, Any]
) -> tuple[Entity, str]:
    container_name = _container_name(container)
    container_id = (
        f"portainer_container:{endpoint_id}:{container.get('Id') or container_name}"
    )
    props = {
        "name": str(container_name).lstrip("/"),
        "image": container.get("Image"),
        "state": container.get("State"),
        "externalToolId": container_id.split(":", 1)[1],
        "domain": CATEGORY,
    }
    entity = Entity(
        id=container_id,
        node_type="AssetInstance",
        properties={k: v for k, v in props.items() if v is not None},
    )
    return entity, container_id


def _stack_entity(stack_id: Any, stack: dict[str, Any]) -> Entity:
    return Entity(
        id=f"portainer_stack:{stack_id}",
        node_type="Service",
        properties={
            "name": stack.get("Name") or stack.get("name") or f"stack-{stack_id}",
            "ci_class": "stack",
            "externalToolId": str(stack_id),
            "domain": CATEGORY,
        },
    )


def _endpoint_changes(
    client: Any, endpoint_id: Any, endpoint: dict[str, Any]
) -> tuple[list[Entity], list[Relationship]]:
    endpoint_entity = _endpoint_entity(endpoint_id, endpoint)
    entities = [endpoint_entity]
    relationships: list[Relationship] = []
    for container in _rows(_safe_call(client, "list_containers", endpoint_id)):
        entity, container_id = _container_entity(endpoint_id, container)
        entities.append(entity)
        relationships.append(
            Relationship(
                source=container_id, target=endpoint_entity.id, relationship="RUNS_ON"
            )
        )
    return entities, relationships


def _changes(client: Any) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for endpoint in _rows(_safe_call(client, "get_endpoints")):
        endpoint_id = endpoint.get("Id") or endpoint.get("id")
        if endpoint_id is None:
            continue
        ents, rels = _endpoint_changes(client, endpoint_id, endpoint)
        entities.extend(ents)
        relationships.extend(rels)
    return entities, relationships


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    entities, relationships = _changes(client)
    for stack in _rows(_safe_call(client, "list_stacks")):
        stack_id = stack.get("Id") or stack.get("id")
        if stack_id is not None:
            entities.append(_stack_entity(stack_id, stack))

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Portainer endpoints/stacks/containers -> KG entities",
)
