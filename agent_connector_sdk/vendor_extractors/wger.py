"""wger wellness vendor extractor (SDK-SOURCE-INGEST-R006.17).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.wger`` onto
this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`: weight
entries and measurements become ``BodyMeasurement`` entities, workout sessions
become ``WorkoutSession`` entities (``PART_OF`` their routine), and nutrition
plans become ``MealPlan`` entities -- the same shape as the agent-utilities
``GraphNode``/``EnrichmentEdge`` source, now rendered as this SDK's
``Entity``/``Relationship`` records. The client is injected through ``config``
and this module performs no I/O of its own.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "wger"
_DOMAIN = "wger"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _rows(res: Any) -> list[dict[str, Any]]:
    """DRF ``{"results": [...]}`` or a bare list -> ``list[dict]``."""
    if isinstance(res, dict):
        res = res.get("results", res.get("data", []))
    return (
        [row for row in res if isinstance(row, dict)] if isinstance(res, list) else []
    )


def _call(client: Any, name: str) -> Any:
    method = getattr(client, name, None)
    try:
        return method() if callable(method) else None
    except Exception:
        return None


def _props(**fields: Any) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def _record_built(
    record: dict[str, Any], *, prefix: str, node_type: str, properties_fn: Any
) -> tuple[str, Entity] | None:
    """A wger entity -- weight/measurement/session/plan all share the same
    id/properties shape, differing only in prefix, label, and which fields
    become display properties."""
    record_id = record.get("id")
    if record_id is None:
        return None
    node_id = f"{prefix}:{record_id}"
    entity = Entity(
        id=node_id,
        node_type=node_type,
        properties=_props(
            **properties_fn(record), externalToolId=str(record_id), domain=_DOMAIN
        ),
    )
    return node_id, entity


def _session_relationship(node_id: str, session: dict[str, Any]) -> Relationship | None:
    routine = session.get("routine")
    if routine is None:
        return None
    return Relationship(
        source=node_id, target=f"wger:routine:{routine}", relationship="PART_OF"
    )


_GROUPS = (
    (
        "get_weight_entries",
        "wger:weight",
        "BodyMeasurement",
        lambda w: {"kind": "weight", "value": w.get("weight"), "date": w.get("date")},
        None,
    ),
    (
        "get_measurements",
        "wger:meas",
        "BodyMeasurement",
        lambda m: {
            "kind": "measurement",
            "category": m.get("category"),
            "value": m.get("value"),
            "date": m.get("date"),
        },
        None,
    ),
    (
        "get_workout_sessions",
        "wger:session",
        "WorkoutSession",
        lambda s: {
            "date": s.get("date"),
            "impression": s.get("impression"),
            "notes": s.get("notes"),
        },
        _session_relationship,
    ),
    (
        "get_nutrition_plans",
        "wger:nutplan",
        "MealPlan",
        lambda p: {
            "description": p.get("description"),
            "only_logging": p.get("only_logging"),
        },
        None,
    ),
)


def _extract_group(
    client: Any,
    *,
    method: str,
    prefix: str,
    node_type: str,
    properties_fn: Any,
    relationship_fn: Any,
) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for record in _rows(_call(client, method)):
        built = _record_built(
            record, prefix=prefix, node_type=node_type, properties_fn=properties_fn
        )
        if built is None:
            continue
        node_id, entity = built
        entities.append(entity)
        relationship = (
            relationship_fn(node_id, record) if relationship_fn is not None else None
        )
        if relationship is not None:
            relationships.append(relationship)
    return entities, relationships


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for method, prefix, node_type, properties_fn, relationship_fn in _GROUPS:
        group_entities, group_relationships = _extract_group(
            client,
            method=method,
            prefix=prefix,
            node_type=node_type,
            properties_fn=properties_fn,
            relationship_fn=relationship_fn,
        )
        entities.extend(group_entities)
        relationships.extend(group_relationships)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="wger wellness (weight/measurements/sessions) -> KG"
)
