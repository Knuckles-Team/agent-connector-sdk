"""Env-var declarations (compose, ``.env.example``, ``mcp_config*.json``) for env_drift."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from scion_sdk.mcp._env_drift_scan import _ENV_NAME

_ENV_DECL = re.compile(r"^\s*#?\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=")
_SUBST = re.compile(r"\$\{([^}]*)\}")
_COMPOSE_SUBST_KEYS = frozenset({"image", "command", "entrypoint", "args"})


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None


def _compose_files(root: Path) -> list[Path]:
    docker = root / "docker"
    files = sorted(docker.glob("*compose*.y*ml")) if docker.is_dir() else []
    return [f for f in files if f.suffix in {".yml", ".yaml"}]


def _compose_services(document: Any) -> list[dict[str, Any]]:
    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, dict):
        return []
    return [s for s in services.values() if isinstance(s, dict)]


def _service_env_keys(service: dict[str, Any]) -> set[str]:
    env = service.get("environment")
    if isinstance(env, dict):
        return {str(k) for k in env}
    if isinstance(env, list):
        return {str(item).split("=", 1)[0].strip() for item in env}
    return set()


def _compose_env_keys(root: Path) -> dict[str, set[str]]:
    """Per compose file, the keys its ``environment:`` blocks declare."""
    out: dict[str, set[str]] = {}
    for path in _compose_files(root):
        keys: set[str] = set()
        for service in _compose_services(_load_yaml(path)):
            keys |= _service_env_keys(service)
        keys = {k for k in keys if _ENV_NAME.fullmatch(k)}
        if keys:
            out[path.name] = keys
    return out


def _subst_names(value: Any) -> set[str]:
    text = " ".join(map(str, value)) if isinstance(value, list) else str(value)
    names: set[str] = set()
    for inner in _SUBST.findall(text):
        name = re.split(r"[:?\-+]", inner.strip(), maxsplit=1)[0]
        if _ENV_NAME.fullmatch(name):
            names.add(name)
    return names


def _compose_subst_reads(root: Path) -> set[str]:
    """``${VAR}`` substitutions compose itself performs outside ``environment:``."""
    found: set[str] = set()
    for path in _compose_files(root):
        for service in _compose_services(_load_yaml(path)):
            for key in _COMPOSE_SUBST_KEYS & set(service):
                found.update(_subst_names(service[key]))
    return found


def _declared_env_example(root: Path) -> set[str]:
    """Variables declared in ``.env.example``."""
    path = root / ".env.example"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {m.group(1) for line in lines if (m := _ENV_DECL.match(line))}


def _server_env_keys(server: Any) -> set[str]:
    env = server.get("env") if isinstance(server, dict) else None
    if not isinstance(env, dict):
        return set()
    return {k for k in env if _ENV_NAME.fullmatch(str(k))}


def _mcp_config_env(root: Path) -> list[tuple[str, set[str]]]:
    """Per ``mcp_config*.json``, the env keys its servers declare."""
    out: list[tuple[str, set[str]]] = []
    for path in sorted(root.glob("mcp_config*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        servers = document.get("mcpServers") if isinstance(document, dict) else None
        keys: set[str] = set()
        if isinstance(servers, dict):
            for server in servers.values():
                keys |= _server_env_keys(server)
        if keys:
            out.append((path.name, keys))
    return out
