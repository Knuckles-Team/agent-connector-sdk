"""Per-connector state directories (SDK-CONNECTOR-CONTROL-R014.7).

Replaces agent-utilities ``core.paths`` for connectors: XDG locations under an
``agent-connectors`` application directory, each overridable by one setting.
No harness paths (skills, prompts, KG databases) live here.
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_connector_sdk.config import setting

__all__ = [
    "cache_dir",
    "config_dir",
    "data_dir",
    "get_mcp_config_path",
    "log_dir",
    "research_dir",
]

MCP_CONFIG_FILE = "mcp_config.json"

APP_DIR = "agent-connectors"


def _xdg(variable: str, fallback: str) -> Path:
    base = os.environ.get(variable) or str(Path.home() / fallback)
    return Path(base) / APP_DIR


def _resolve(override: str, default: Path) -> Path:
    raw = setting(override, "")
    path = Path(str(raw)).expanduser() if raw else default
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """``CONNECTOR_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/agent-connectors``."""
    return _resolve("CONNECTOR_CONFIG_DIR", _xdg("XDG_CONFIG_HOME", ".config"))


def data_dir() -> Path:
    """``CONNECTOR_DATA_DIR`` or ``$XDG_DATA_HOME/agent-connectors``."""
    return _resolve("CONNECTOR_DATA_DIR", _xdg("XDG_DATA_HOME", ".local/share"))


def cache_dir() -> Path:
    """``CONNECTOR_CACHE_DIR`` or ``$XDG_CACHE_HOME/agent-connectors``."""
    return _resolve("CONNECTOR_CACHE_DIR", _xdg("XDG_CACHE_HOME", ".cache"))


def log_dir() -> Path:
    """``CONNECTOR_LOG_DIR`` or ``$XDG_STATE_HOME/agent-connectors/logs``."""
    return _resolve(
        "CONNECTOR_LOG_DIR", _xdg("XDG_STATE_HOME", ".local/state") / "logs"
    )


def research_dir() -> Path:
    """``CONNECTOR_RESEARCH_DIR`` or ``data_dir()/research``."""
    return _resolve("CONNECTOR_RESEARCH_DIR", data_dir() / "research")


def get_mcp_config_path() -> str | None:
    """The connector's ``mcp_config.json`` under :func:`config_dir`, if present."""
    path = config_dir() / MCP_CONFIG_FILE
    return str(path) if path.is_file() else None
