"""wger wellness vendor extractor (SCION-SOURCE-INGEST-R006.17).

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
from agent_connector_sdk.vendor_extractors._records import _get, _props, _safe_call
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "wger"
_DOMAIN = "wger"


def _rows(res: Any) -> list[dict[str, Any]]:
    """DRF ``{"results": [...]}`` or a bare list -> ``list[dict]``."""
    if isinstance(res, dict):
        res = res.get("results", res.get("data", []))
    return (
        [row for row in res if isinstance(row, dict)] if isinstance(res, list) else []
    )


def _body_entities(
    rows: list[dict[str, Any]], label: tuple[str, str], fields: dict[str, str]
) -> list[Entity]:
    """BodyMeasurement entities for ``rows``; ``label`` is (id infix, kind)."""
    infix, kind = label
    entities: list[Entity] = []
    for row in rows:
        row_id = row.get("id")
        if row_id is None:
            continue
        props = {prop: row.get(key) for prop, key in fields.items()}
        entities.append(
            Entity(
                id=f"wger:{infix}:{row_id}",
                node_type="BodyMeasurement",
                properties=_props(
                    kind=kind, **props, externalToolId=str(row_id), domain=_DOMAIN
                ),
            )
        )
    return entities


def _weights(client: Any) -> list[Entity]:
    rows = _rows(_safe_call(client, "get_weight_entries"))
    return _body_entities(
        rows, ("weight", "weight"), {"value": "weight", "date": "date"}
    )


def _measurements(client: Any) -> list[Entity]:
    rows = _rows(_safe_call(client, "get_measurements"))
    fields = {"category": "category", "value": "value", "date": "date"}
    return _body_entities(rows, ("meas", "measurement"), fields)


def _sessions(client: Any) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    for session in _rows(_safe_call(client, "get_workout_sessions")):
        session_id = session.get("id")
        if session_id is None:
            continue
        node_id = f"wger:session:{session_id}"
        entities.append(
            Entity(
                id=node_id,
                node_type="WorkoutSession",
                properties=_props(
                    date=session.get("date"),
                    impression=session.get("impression"),
                    notes=session.get("notes"),
                    externalToolId=str(session_id),
                    domain=_DOMAIN,
                ),
            )
        )
        routine = session.get("routine")
        if routine is not None:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"wger:routine:{routine}",
                    relationship="PART_OF",
                )
            )
    return entities, relationships


def _plans(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for plan in _rows(_safe_call(client, "get_nutrition_plans")):
        plan_id = plan.get("id")
        if plan_id is None:
            continue
        entities.append(
            Entity(
                id=f"wger:nutplan:{plan_id}",
                node_type="MealPlan",
                properties=_props(
                    description=plan.get("description"),
                    only_logging=plan.get("only_logging"),
                    externalToolId=str(plan_id),
                    domain=_DOMAIN,
                ),
            )
        )
    return entities


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    session_entities, relationships = _sessions(client)
    entities = [
        *_weights(client),
        *_measurements(client),
        *session_entities,
        *_plans(client),
    ]
    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="wger wellness (weight/measurements/sessions) -> KG"
)
