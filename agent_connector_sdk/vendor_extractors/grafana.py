"""Grafana observability vendor extractor (SDK-SOURCE-INGEST-R006.23).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.grafana``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
dashboards, panels, alert rules, and datasources become typed entities. The
Grafana client is injected (duck-typed) via ``config["client"]`` and is
expected to expose list-returning ``dashboards()``, ``alert_rules()``, and
``datasources()`` methods. All field access is tolerant; this module performs
no network calls itself.
"""

from __future__ import annotations

import re
from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "grafana"


def _get(record: Any, key: str, default: Any = None) -> Any:
    """Tolerant field access for dict records (or attr-style objects)."""
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _call(client: Any, name: str) -> list[Any]:
    """Call a client method if present, returning a list (tolerant)."""
    method = getattr(client, name, None)
    if not callable(method):
        return []
    result = method()
    return list(result) if result else []


def _scalar(value: Any) -> str | None:
    """Normalise a value to a non-empty scalar string, else ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _service_from_labels(labels: Any) -> str | None:
    """Pull a service name from a labels mapping (service/app/job keys)."""
    if not isinstance(labels, dict):
        return None
    for key in ("service", "app", "job", "service_name"):
        name = _scalar(labels.get(key))
        if name:
            return name
    return None


def _service_from_title(title: Any) -> str | None:
    """Heuristically pull a service token from an explicit title marker."""
    text = _scalar(title)
    if not text:
        return None
    match = re.search(r"service\s*[:=]\s*([A-Za-z0-9._-]+)", text, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_datasources(client: Any, entities: list[Entity]) -> None:
    """Append ``DataSource`` entities for every client-reported datasource."""
    for datasource in _call(client, "datasources"):
        uid = _scalar(_get(datasource, "uid")) or _scalar(_get(datasource, "name"))
        if not uid:
            continue
        entities.append(
            Entity(
                id=f"datasource:{uid}",
                node_type="DataSource",
                properties={
                    key: value
                    for key, value in (
                        ("name", _get(datasource, "name")),
                        ("ds_type", _scalar(_get(datasource, "type"))),
                    )
                    if value is not None
                },
            )
        )


def _extract_panel(
    panel: Any,
    dash_uid: str,
    dash_id: str,
    *,
    entities: list[Entity],
    relationships: list[Relationship],
) -> None:
    """Append a dashboard's ``Panel`` entity plus its ``PART_OF``/``MONITORS`` edges."""
    panel_id = _scalar(_get(panel, "id")) or _scalar(_get(panel, "panel_id"))
    if not panel_id:
        return
    node_id = f"panel:{dash_uid}:{panel_id}"
    targets = _get(panel, "targets", []) or []
    entities.append(
        Entity(
            id=node_id,
            node_type="Panel",
            properties={
                "title": _get(panel, "title"),
                "targets": list(targets),
            },
        )
    )
    relationships.append(
        Relationship(source=node_id, target=dash_id, relationship="PART_OF")
    )
    service = _service_from_labels(_get(panel, "labels")) or _service_from_title(
        _get(panel, "title")
    )
    if service:
        relationships.append(
            Relationship(
                source=node_id,
                target=f"service:{service}",
                relationship="MONITORS",
            )
        )


def _extract_dashboards(
    client: Any, entities: list[Entity], relationships: list[Relationship]
) -> None:
    """Append ``Dashboard`` entities and their panels for every client dashboard."""
    for dashboard in _call(client, "dashboards"):
        dash_uid = _scalar(_get(dashboard, "uid"))
        if not dash_uid:
            continue
        dash_id = f"dashboard:{dash_uid}"
        entities.append(
            Entity(
                id=dash_id,
                node_type="Dashboard",
                properties={"title": _get(dashboard, "title")}
                if _get(dashboard, "title") is not None
                else {},
            )
        )
        for panel in _get(dashboard, "panels", []) or []:
            _extract_panel(
                panel, dash_uid, dash_id, entities=entities, relationships=relationships
            )


def _extract_alerts(
    client: Any, entities: list[Entity], relationships: list[Relationship]
) -> None:
    """Append ``Alert`` entities and their ``MONITORS`` edges for every alert rule."""
    for alert in _call(client, "alert_rules"):
        uid = _scalar(_get(alert, "uid"))
        if not uid:
            continue
        node_id = f"alert:{uid}"
        entities.append(
            Entity(
                id=node_id,
                node_type="Alert",
                properties={
                    key: value
                    for key, value in (
                        ("title", _get(alert, "title")),
                        ("condition", _scalar(_get(alert, "condition"))),
                    )
                    if value is not None
                },
            )
        )
        service = _service_from_labels(_get(alert, "labels")) or _service_from_title(
            _get(alert, "title")
        )
        if service:
            relationships.append(
                Relationship(
                    source=node_id,
                    target=f"service:{service}",
                    relationship="MONITORS",
                )
            )


def extract(config: Any) -> ChangeSet:
    """Extract Grafana observability objects into a uniform ``ChangeSet``.

    Dashboards become ``Dashboard`` entities; panels become ``Panel`` entities
    linked ``PART_OF`` their dashboard. Alerts and datasources become
    ``Alert`` and ``DataSource`` entities. Panels/alerts referencing a service
    (via labels or an explicit ``service=`` title marker) emit a ``MONITORS``
    relationship to ``service:<name>``.
    """
    client = _get(config, "client")
    if client is None:
        return ChangeSet()

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    _extract_datasources(client, entities)
    _extract_dashboards(client, entities, relationships)
    _extract_alerts(client, entities, relationships)

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Grafana dashboards/alerts/datasources -> KG",
)
