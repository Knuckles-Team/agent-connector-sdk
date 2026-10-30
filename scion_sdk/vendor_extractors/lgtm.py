"""LGTM (Grafana/Loki/Tempo/Mimir) vendor extractor (SCION-SOURCE-INGEST-R006.8).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.lgtm``
onto this SDK's typed :mod:`~scion_sdk.vendor_extractors.contract`:
dashboards, alerts, and datasources become ``Dashboard``/``Alert``/
``DataSource`` entities instead of agent-utilities' ``GraphNode``. The client
is injected through ``config`` and this module performs no I/O of its own.
"""

from __future__ import annotations

from typing import Any

from scion_sdk.ingest import ChangeSet, Entity
from scion_sdk.vendor_extractors._extract_common import (
    _call_dict_rows,
    _client_changeset,
    _entity_of,
)
from scion_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "lgtm"


def _dashboards(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for dashboard in _call_dict_rows(client, "get_dashboards", unwrap=True):
        uid = dashboard.get("uid") or dashboard.get("id") or dashboard.get("title")
        if not uid:
            continue
        fields = {
            "name": dashboard.get("title") or str(uid),
            "externalToolId": str(uid),
            "domain": CATEGORY,
        }
        entities.append(_entity_of(f"lgtm_dash:{uid}", "Dashboard", fields))
    return entities


def _alert_id(alert: Any) -> Any:
    return (
        alert.get("fingerprint")
        or alert.get("id")
        or (alert.get("labels") or {}).get("alertname")
    )


def _alert_entity(alert: Any, alert_id: Any) -> Entity:
    fields = {
        "name": (alert.get("labels") or {}).get("alertname") or str(alert_id),
        "state": alert.get("status") or alert.get("state"),
        "externalToolId": str(alert_id),
        "domain": CATEGORY,
    }
    return _entity_of(f"lgtm_alert:{alert_id}", "Alert", fields)


def _alerts(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for alert in _call_dict_rows(client, "get_alerts", unwrap=True):
        alert_id = _alert_id(alert)
        if not alert_id:
            continue
        entities.append(_alert_entity(alert, alert_id))
    return entities


def _datasources(client: Any) -> list[Entity]:
    entities: list[Entity] = []
    for datasource in _call_dict_rows(client, "list_datasources", unwrap=True):
        ds_id = datasource.get("uid") or datasource.get("id") or datasource.get("name")
        if not ds_id:
            continue
        fields = {
            "name": datasource.get("name") or str(ds_id),
            "ds_type": datasource.get("type"),
            "externalToolId": str(ds_id),
            "domain": CATEGORY,
        }
        entities.append(_entity_of(f"lgtm_ds:{ds_id}", "DataSource", fields))
    return entities


def extract(config: Any) -> ChangeSet:
    return _client_changeset(
        config,
        lambda client: [*_dashboards(client), *_alerts(client), *_datasources(client)],
    )


register_vendor_extractor(
    CATEGORY, extract, description="LGTM dashboards/alerts/datasources -> KG entities"
)
