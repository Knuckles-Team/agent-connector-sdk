"""LGTM (Grafana/Loki/Tempo/Mimir) vendor extractor (SDK-SOURCE-INGEST-R006.8).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.lgtm``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
dashboards, alerts, and datasources become ``Dashboard``/``Alert``/
``DataSource`` entities instead of agent-utilities' ``GraphNode``. The client
is injected through ``config`` and this module performs no I/O of its own.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "lgtm"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _call(client: Any, name: str) -> list[dict[str, Any]]:
    method = getattr(client, name, None)
    try:
        result = method() if callable(method) else None
    except Exception:
        return []
    if isinstance(result, dict):
        result = result.get("data") or result.get("value") or list(result.values())
    return (
        [row for row in result if isinstance(row, dict)]
        if isinstance(result, list)
        else []
    )


def _dashboards(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for dashboard in _call(client, "get_dashboards"):
        uid = dashboard.get("uid") or dashboard.get("id") or dashboard.get("title")
        if not uid:
            continue
        entities.append(
            Entity(
                id=f"lgtm_dash:{uid}",
                node_type="Dashboard",
                properties={
                    "name": dashboard.get("title") or str(uid),
                    "externalToolId": str(uid),
                    "domain": CATEGORY,
                },
            )
        )
    return entities


def _alerts(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for alert in _call(client, "get_alerts"):
        alert_id = (
            alert.get("fingerprint")
            or alert.get("id")
            or (alert.get("labels") or {}).get("alertname")
        )
        if not alert_id:
            continue
        entities.append(
            Entity(
                id=f"lgtm_alert:{alert_id}",
                node_type="Alert",
                properties={
                    key: value
                    for key, value in {
                        "name": (alert.get("labels") or {}).get("alertname")
                        or str(alert_id),
                        "state": alert.get("status") or alert.get("state"),
                        "externalToolId": str(alert_id),
                        "domain": CATEGORY,
                    }.items()
                    if value is not None
                },
            )
        )
    return entities


def _datasources(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for datasource in _call(client, "list_datasources"):
        ds_id = datasource.get("uid") or datasource.get("id") or datasource.get("name")
        if not ds_id:
            continue
        entities.append(
            Entity(
                id=f"lgtm_ds:{ds_id}",
                node_type="DataSource",
                properties={
                    key: value
                    for key, value in {
                        "name": datasource.get("name") or str(ds_id),
                        "ds_type": datasource.get("type"),
                        "externalToolId": str(ds_id),
                        "domain": CATEGORY,
                    }.items()
                    if value is not None
                },
            )
        )
    return entities


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    entities = [*_dashboards(client), *_alerts(client), *_datasources(client)]
    return ChangeSet(entities=tuple(entities))


register_vendor_extractor(
    CATEGORY, extract, description="LGTM dashboards/alerts/datasources -> KG entities"
)
