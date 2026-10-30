"""Grafana observability vendor extractor (SCION-SOURCE-INGEST-R006.23).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.grafana``
onto this SDK's typed :mod:`~scion_sdk.vendor_extractors.contract`:
dashboards, panels, alert rules, and datasources become typed entities. The
Grafana client is injected (duck-typed) via ``config["client"]`` and is
expected to expose list-returning ``dashboards()``, ``alert_rules()``, and
``datasources()`` methods. All field access is tolerant; this module performs
no network calls itself.
"""

from __future__ import annotations

from typing import Any

from scion_sdk.ingest import ChangeSet, Entity, Relationship
from scion_sdk.vendor_extractors.contract import register_vendor_extractor
from scion_sdk.vendor_extractors.grafana_helpers import (
    _scalar,
    _service_from_labels,
    _service_from_title,
)
from scion_sdk.vendor_extractors.grafana_helpers import (
    call as _call,
)
from scion_sdk.vendor_extractors.grafana_helpers import (
    get as _get,
)

CATEGORY = "grafana"


def _props(*pairs: tuple[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in pairs if value is not None}


def _monitors(source: str, record: Any) -> list[Relationship]:
    service = _service_from_labels(_get(record, "labels")) or _service_from_title(
        _get(record, "title")
    )
    if not service:
        return []
    return [
        Relationship(
            source=source, target=f"service:{service}", relationship="MONITORS"
        )
    ]


def _datasources(client: Any) -> list[Entity]:
    out: list[Entity] = []
    for datasource in _call(client, "datasources"):
        uid = _scalar(_get(datasource, "uid")) or _scalar(_get(datasource, "name"))
        if not uid:
            continue
        properties = _props(
            ("name", _get(datasource, "name")),
            ("ds_type", _scalar(_get(datasource, "type"))),
        )
        out.append(
            Entity(
                id=f"datasource:{uid}", node_type="DataSource", properties=properties
            )
        )
    return out


def _panel(
    dash_uid: str, dash_id: str, panel: Any
) -> tuple[Entity, list[Relationship]] | None:
    panel_id = _scalar(_get(panel, "id")) or _scalar(_get(panel, "panel_id"))
    if not panel_id:
        return None
    node_id = f"panel:{dash_uid}:{panel_id}"
    targets = _get(panel, "targets", []) or []
    entity = Entity(
        id=node_id,
        node_type="Panel",
        properties={"title": _get(panel, "title"), "targets": list(targets)},
    )
    rels = [Relationship(source=node_id, target=dash_id, relationship="PART_OF")]
    return entity, rels + _monitors(node_id, panel)


def _dashboards(client: Any) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    rels: list[Relationship] = []
    for dashboard in _call(client, "dashboards"):
        dash_uid = _scalar(_get(dashboard, "uid"))
        if not dash_uid:
            continue
        dash_id = f"dashboard:{dash_uid}"
        title = _get(dashboard, "title")
        entities.append(
            Entity(
                id=dash_id,
                node_type="Dashboard",
                properties={"title": title} if title is not None else {},
            )
        )
        for panel in _get(dashboard, "panels", []) or []:
            built = _panel(dash_uid, dash_id, panel)
            if built is not None:
                entities.append(built[0])
                rels.extend(built[1])
    return entities, rels


def _alerts(client: Any) -> tuple[list[Entity], list[Relationship]]:
    entities: list[Entity] = []
    rels: list[Relationship] = []
    for alert in _call(client, "alert_rules"):
        uid = _scalar(_get(alert, "uid"))
        if not uid:
            continue
        node_id = f"alert:{uid}"
        properties = _props(
            ("title", _get(alert, "title")),
            ("condition", _scalar(_get(alert, "condition"))),
        )
        entities.append(Entity(id=node_id, node_type="Alert", properties=properties))
        rels.extend(_monitors(node_id, alert))
    return entities, rels


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

    entities = _datasources(client)
    dash_entities, relationships = _dashboards(client)
    alert_entities, alert_rels = _alerts(client)
    entities.extend(dash_entities)
    entities.extend(alert_entities)
    relationships.extend(alert_rels)
    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="Grafana dashboards/alerts/datasources -> KG",
)
