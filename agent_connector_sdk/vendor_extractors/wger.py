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


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    for weight in _rows(_call(client, "get_weight_entries")):
        weight_id = weight.get("id")
        if weight_id is None:
            continue
        entities.append(
            Entity(
                id=f"wger:weight:{weight_id}",
                node_type="BodyMeasurement",
                properties=_props(
                    kind="weight",
                    value=weight.get("weight"),
                    date=weight.get("date"),
                    externalToolId=str(weight_id),
                    domain=_DOMAIN,
                ),
            )
        )

    for measurement in _rows(_call(client, "get_measurements")):
        measurement_id = measurement.get("id")
        if measurement_id is None:
            continue
        entities.append(
            Entity(
                id=f"wger:meas:{measurement_id}",
                node_type="BodyMeasurement",
                properties=_props(
                    kind="measurement",
                    category=measurement.get("category"),
                    value=measurement.get("value"),
                    date=measurement.get("date"),
                    externalToolId=str(measurement_id),
                    domain=_DOMAIN,
                ),
            )
        )

    for session in _rows(_call(client, "get_workout_sessions")):
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

    for plan in _rows(_call(client, "get_nutrition_plans")):
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

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY, extract, description="wger wellness (weight/measurements/sessions) -> KG"
)
