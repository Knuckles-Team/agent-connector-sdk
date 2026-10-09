"""Caddy reverse-proxy vendor extractor (SDK-SOURCE-INGEST-R006.3).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.caddy``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
HTTP server routes become ``Service`` entities instead of agent-utilities'
``GraphNode``. The client is injected through ``config`` and this module
performs no I/O of its own; it is tolerant of the Caddy JSON config shape.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor

CATEGORY = "caddy"


def _get(config: Any, key: str) -> Any:
    return config.get(key) if isinstance(config, dict) else getattr(config, key, None)


def _route_hosts(route: dict[str, Any]) -> list[str]:
    hosts: list[str] = []
    for match in route.get("match", []) or []:
        if isinstance(match, dict):
            hosts.extend(match.get("host", []) or [])
    return hosts


def _config(client: Any) -> dict[str, Any] | None:
    getter = getattr(client, "get_config", None)
    if not callable(getter):
        return None
    try:
        cfg = getter("")
    except Exception:
        return None
    return cfg if isinstance(cfg, dict) else None


def _entities(cfg: dict[str, Any]) -> list[Entity]:
    servers = ((cfg.get("apps") or {}).get("http") or {}).get("servers") or {}
    entities: list[Entity] = []
    for server_name, server in servers.items() if isinstance(servers, dict) else []:
        for index, route in enumerate(server.get("routes", []) or []):
            if not isinstance(route, dict):
                continue
            hosts = _route_hosts(route)
            label = hosts[0] if hosts else f"{server_name}-route-{index}"
            route_id = f"caddy_route:{server_name}:{label}"
            properties = {
                "name": label,
                "ci_class": "reverse_proxy_route",
                "hosts": ",".join(hosts) or None,
                "server": server_name,
                "externalToolId": route_id.split(":", 1)[1],
                "domain": CATEGORY,
            }
            entities.append(
                Entity(
                    id=route_id,
                    node_type="Service",
                    properties={
                        key: value
                        for key, value in properties.items()
                        if value is not None
                    },
                )
            )
    return entities


def extract(config: Any) -> ChangeSet:
    client = _get(config, "client")
    if client is None:
        return ChangeSet()
    cfg = _config(client)
    if cfg is None:
        return ChangeSet()
    return ChangeSet(entities=tuple(_entities(cfg)))


register_vendor_extractor(
    CATEGORY, extract, description="Caddy reverse-proxy routes -> KG entities"
)
