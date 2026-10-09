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
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "portainer"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _call(client: Any, name: str, *args: Any) -> Any:
    method = getattr(client, name, None)
    try:
        return method(*args) if callable(method) else None
    except Exception:
        return None


def _rows(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        result = result.get("data") or result.get("value") or []
    return (
        [row for row in result if isinstance(row, dict)]
        if isinstance(result, list)
        else []
    )


def _endpoint_entity(
    endpoint: dict[str, Any], endpoint_id: Any, endpoint_node: str
) -> Entity:
    return Entity(
        id=endpoint_node,
        node_type="Server",
        properties={
            "name": endpoint.get("Name")
            or endpoint.get("name")
            or f"endpoint-{endpoint_id}",
            "externalToolId": str(endpoint_id),
            "domain": CATEGORY,
        },
    )


def _container_entity_and_relationship(
    container: dict[str, Any], endpoint_id: Any, endpoint_node: str
) -> tuple[Entity, Relationship]:
    names = container.get("Names") or [container.get("name")]
    container_name = (
        names[0]
        if isinstance(names, list) and names
        else container.get("Id") or "container"
    )
    container_id = (
        f"portainer_container:{endpoint_id}:{container.get('Id') or container_name}"
    )
    entity = Entity(
        id=container_id,
        node_type="AssetInstance",
        properties={
            key: value
            for key, value in {
                "name": str(container_name).lstrip("/"),
                "image": container.get("Image"),
                "state": container.get("State"),
                "externalToolId": container_id.split(":", 1)[1],
                "domain": CATEGORY,
            }.items()
            if value is not None
        },
    )
    relationship = Relationship(
        source=container_id, target=endpoint_node, relationship="RUNS_ON"
    )
    return entity, relationship


def _containers_for_endpoint(
    client: Any, endpoint_id: Any, endpoint_node: str
) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for container in _rows(_call(client, "list_containers", endpoint_id)):
        entity, relationship = _container_entity_and_relationship(
            container, endpoint_id, endpoint_node
        )
        entities.append(entity)
        relationships.append(relationship)
    return entities, relationships


def _endpoints_and_containers(
    client: Any,
) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for endpoint in _rows(_call(client, "get_endpoints")):
        endpoint_id = endpoint.get("Id") or endpoint.get("id")
        if endpoint_id is None:
            continue
        endpoint_node = f"portainer_endpoint:{endpoint_id}"
        entities.append(_endpoint_entity(endpoint, endpoint_id, endpoint_node))
        container_entities, container_relationships = _containers_for_endpoint(
            client, endpoint_id, endpoint_node
        )
        entities.extend(container_entities)
        relationships.extend(container_relationships)
    return entities, relationships


def _stack_entities(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for stack in _rows(_call(client, "list_stacks")):
        stack_id = stack.get("Id") or stack.get("id")
        if stack_id is None:
            continue
        entities.append(
            Entity(
                id=f"portainer_stack:{stack_id}",
                node_type="Service",
                properties={
                    "name": stack.get("Name")
                    or stack.get("name")
                    or f"stack-{stack_id}",
                    "ci_class": "stack",
                    "externalToolId": str(stack_id),
                    "domain": CATEGORY,
                },
            )
        )
    return entities


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities, relationships = _endpoints_and_containers(client)
    entities.extend(_stack_entities(client))

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Portainer endpoints/stacks/containers -> KG entities",
)
