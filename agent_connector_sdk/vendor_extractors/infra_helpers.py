"""Inventory-parsing helpers for the infra extractor."""

from __future__ import annotations

from typing import Any


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


def _absorb(hosts: dict[str, dict[str, Any]], mapping: Any) -> None:
    if not isinstance(mapping, dict):
        return
    for name, host_vars in mapping.items():
        if not isinstance(name, str):
            continue
        hosts[name] = host_vars if isinstance(host_vars, dict) else {}


def _walk(hosts: dict[str, dict[str, Any]], node: Any) -> None:
    if not isinstance(node, dict):
        return
    if isinstance(node.get("hosts"), dict):
        _absorb(hosts, node["hosts"])
    children = node.get("children")
    if isinstance(children, dict):
        for child in children.values():
            _walk(hosts, child)


def _absorb_flat(hosts: dict[str, dict[str, Any]], inventory: dict[str, Any]) -> None:
    for name, host_vars in inventory.items():
        if not isinstance(name, str) or name in ("vars", "children"):
            continue
        if isinstance(host_vars, dict):
            hosts[name] = host_vars


def _iter_host_maps(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalise tolerant inventory shapes into ``{host_name: host_vars}``.

    Handles a flat ``{host: {ip: ...}}`` mapping, an Ansible
    ``{all: {hosts: {host: {...}}}}`` shape (with nested ``children``), and a
    top-level ``hosts:``/``tunnels:`` mapping.
    """
    hosts: dict[str, dict[str, Any]] = {}
    grouped = False
    top = inventory.get("all")
    if isinstance(top, dict) and ("hosts" in top or "children" in top):
        _walk(hosts, top)
        grouped = True
    for key in ("hosts", "tunnels"):
        if isinstance(inventory.get(key), dict):
            _absorb(hosts, inventory[key])
            grouped = True
    if not grouped:
        _absorb_flat(hosts, inventory)
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
