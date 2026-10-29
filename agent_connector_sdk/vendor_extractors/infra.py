"""Infrastructure inventory vendor extractor (SCION-SOURCE-INGEST-R006.21).

Ported from ``agent_utilities.knowledge_graph.enrichment.extractors.infra``
onto this SDK's typed :mod:`~agent_connector_sdk.vendor_extractors.contract`:
tunnel-manager ``inventory.yaml`` hosts become ``Server`` entities and Docker
services become ``Service`` entities, wired by ``RUNS_ON`` relationships.

Pure and deterministic: this module never opens a network socket. It accepts
an already-parsed inventory dict (or a path to a YAML file, parsed with
:func:`yaml.safe_load`) plus an optional list of service descriptors.

``config`` may be a dict or any attribute-bearing object with:
  * ``inventory`` -- a parsed inventory mapping OR a path string to a YAML file.
  * ``services``  -- optional list of dicts ``{"name","image","replicas","node"}``.
"""

from __future__ import annotations

from typing import Any

from agent_connector_sdk.ingest import ChangeSet, Entity, Relationship
from agent_connector_sdk.vendor_extractors.contract import register_vendor_extractor
from agent_connector_sdk.vendor_extractors.infra_helpers import (
    _as_list,
    _first,
    _get,
    _iter_host_maps,
    _load_inventory,
)

CATEGORY = "infra"

# Common Ansible/tunnel-manager keys for a host's address.
_IP_KEYS = ("ansible_host", "ip", "ansible_ssh_host", "host", "address")
# Common keys naming the host a service runs on.
_NODE_KEYS = ("node", "host", "server", "hostname", "placement")


def _server_entity(name: str, host_vars: dict[str, Any]) -> Entity:
    ip = _first(host_vars, _IP_KEYS)
    return Entity(
        id=f"server:{name}",
        node_type="Server",
        properties={
            "hostname": name,
            "ip": str(ip) if ip is not None else None,
            "roles": _as_list(host_vars.get("roles") or host_vars.get("role")),
            "groups": _as_list(host_vars.get("groups") or host_vars.get("group")),
        },
    )


def _service_parts(service: Any) -> tuple[Entity, Relationship | None] | None:
    if not isinstance(service, dict):
        return None
    service_name = service.get("name")
    if not service_name:
        return None
    service_id = f"service:{service_name}"
    replicas = service.get("replicas")
    entity = Entity(
        id=service_id,
        node_type="Service",
        properties={
            "image": service.get("image"),
            "replicas": int(replicas) if replicas is not None else None,
        },
    )
    node_name = _first(service, _NODE_KEYS)
    if not node_name:
        return entity, None
    return entity, Relationship(
        source=service_id,
        target=f"server:{node_name}",
        relationship="RUNS_ON",
    )


def extract(config: Any) -> ChangeSet:
    """Build a ``ChangeSet`` of Servers, Services, and ``RUNS_ON`` edges."""
    inventory = _load_inventory(_get(config, "inventory"))
    services = _get(config, "services") or []

    entities: list[Entity] = [
        _server_entity(name, host_vars)
        for name, host_vars in _iter_host_maps(inventory).items()
    ]
    relationships: list[Relationship] = []

    for service in services:
        parts = _service_parts(service)
        if parts is None:
            continue
        entities.append(parts[0])
        if parts[1] is not None:
            relationships.append(parts[1])

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="tunnel-manager inventory + Docker services -> KG",
)
