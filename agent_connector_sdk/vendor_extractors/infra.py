"""Infrastructure inventory vendor extractor (SDK-SOURCE-INGEST-R006.21).

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

CATEGORY = "infra"

# Common Ansible/tunnel-manager keys for a host's address.
_IP_KEYS = ("ansible_host", "ip", "ansible_ssh_host", "host", "address")
# Common keys naming the host a service runs on.
_NODE_KEYS = ("node", "host", "server", "hostname", "placement")


def _get(config: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dict-like or attribute-bearing config object."""
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _load_inventory(inventory: Any) -> dict[str, Any]:
    """Return a parsed inventory mapping from a dict or a YAML path string."""
    if inventory is None:
        return {}
    if isinstance(inventory, str):
        import yaml

        with open(inventory, encoding="utf-8") as handle:
            inventory = yaml.safe_load(handle) or {}
    if not isinstance(inventory, dict):
        return {}
    return inventory


def _iter_host_maps(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalise tolerant inventory shapes into ``{host_name: host_vars}``.

    Handles a flat ``{host: {ip: ...}}`` mapping, an Ansible
    ``{all: {hosts: {host: {...}}}}`` shape (with nested ``children``), and a
    top-level ``hosts:``/``tunnels:`` mapping.
    """
    hosts: dict[str, dict[str, Any]] = {}

    def _absorb(mapping: Any) -> None:
        if not isinstance(mapping, dict):
            return
        for name, host_vars in mapping.items():
            if not isinstance(name, str):
                continue
            hosts[name] = host_vars if isinstance(host_vars, dict) else {}

    def _walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if isinstance(node.get("hosts"), dict):
            _absorb(node["hosts"])
        children = node.get("children")
        if isinstance(children, dict):
            for child in children.values():
                _walk(child)

    grouped = False
    if isinstance(inventory.get("all"), dict) and (
        "hosts" in inventory["all"] or "children" in inventory["all"]
    ):
        _walk(inventory["all"])
        grouped = True
    if isinstance(inventory.get("hosts"), dict):
        _absorb(inventory["hosts"])
        grouped = True
    if isinstance(inventory.get("tunnels"), dict):
        _absorb(inventory["tunnels"])
        grouped = True

    if not grouped:
        for name, host_vars in inventory.items():
            if not isinstance(name, str) or name in ("vars", "children"):
                continue
            if isinstance(host_vars, dict):
                hosts[name] = host_vars
    return hosts


def _first(host_vars: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in host_vars and host_vars[key] not in (None, ""):
            return host_vars[key]
    return None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def extract(config: Any) -> ChangeSet:
    """Build a ``ChangeSet`` of Servers, Services, and ``RUNS_ON`` edges."""
    inventory = _load_inventory(_get(config, "inventory"))
    services = _get(config, "services") or []

    entities: list[Entity] = []
    relationships: list[Relationship] = []

    for name, host_vars in _iter_host_maps(inventory).items():
        server_id = f"server:{name}"
        ip = _first(host_vars, _IP_KEYS)
        roles = _as_list(host_vars.get("roles") or host_vars.get("role"))
        groups = _as_list(host_vars.get("groups") or host_vars.get("group"))
        entities.append(
            Entity(
                id=server_id,
                node_type="Server",
                properties={
                    "hostname": name,
                    "ip": str(ip) if ip is not None else None,
                    "roles": roles,
                    "groups": groups,
                },
            )
        )

    for service in services:
        if not isinstance(service, dict):
            continue
        service_name = service.get("name")
        if not service_name:
            continue
        service_id = f"service:{service_name}"
        replicas = service.get("replicas")
        entities.append(
            Entity(
                id=service_id,
                node_type="Service",
                properties={
                    "image": service.get("image"),
                    "replicas": int(replicas) if replicas is not None else None,
                },
            )
        )
        node_name = _first(service, _NODE_KEYS)
        if node_name:
            relationships.append(
                Relationship(
                    source=service_id,
                    target=f"server:{node_name}",
                    relationship="RUNS_ON",
                )
            )

    return ChangeSet(entities=tuple(entities), relationships=tuple(relationships))


register_vendor_extractor(
    CATEGORY,
    extract,
    description="tunnel-manager inventory + Docker services -> KG",
)
