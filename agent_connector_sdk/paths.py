"""Per-connector state directories (SDK-CONNECTOR-CONTROL-R014.7).

Replaces agent-utilities ``core.paths`` for connectors: XDG locations under an
``agent-connectors`` application directory, each overridable by one setting.
No harness paths (skills, prompts, KG databases) live here.

:func:`platform_config_dir` / :func:`platform_config_file` resolve the shared
Graph OS platform configuration (``workspace.yml``, ``config.json``, ...).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agent_connector_sdk.config import setting

__all__ = [
    "cache_dir",
    "config_dir",
    "data_dir",
    "get_mcp_config_path",
    "legacy_platform_config_dir",
    "log_dir",
    "platform_config_dir",
    "platform_config_file",
    "preferred_platform_config_dir",
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


# --- Platform (Graph OS) configuration directory ---------------------------
#
# Graph OS owns the platform configuration location: ``GRAPH_OS_CONFIG_DIR``
# or ``$XDG_CONFIG_HOME/graph-os``. For one release, a file that is absent
# there is read from the legacy agent-utilities location
# (``AGENT_UTILITIES_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/agent-utilities``),
# and a single deprecation warning names both paths.

PLATFORM_CONFIG_DIR_SETTING = "GRAPH_OS_CONFIG_DIR"
LEGACY_PLATFORM_CONFIG_DIR_SETTING = "AGENT_UTILITIES_CONFIG_DIR"
PLATFORM_APP_DIR = "graph-os"
LEGACY_PLATFORM_APP_DIR = "agent-utilities"

_logger = logging.getLogger(__name__)
_legacy_warned = False


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _dir_from(setting_name: str, app_dir: str) -> Path:
    raw = os.environ.get(setting_name)
    return Path(raw).expanduser() if raw else _config_home() / app_dir


def preferred_platform_config_dir() -> Path:
    """``GRAPH_OS_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/graph-os`` (no fallback)."""
    return _dir_from(PLATFORM_CONFIG_DIR_SETTING, PLATFORM_APP_DIR)


def legacy_platform_config_dir() -> Path:
    """``AGENT_UTILITIES_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/agent-utilities``."""
    return _dir_from(LEGACY_PLATFORM_CONFIG_DIR_SETTING, LEGACY_PLATFORM_APP_DIR)


def _warn_legacy(new: Path, old: Path) -> None:
    global _legacy_warned
    if _legacy_warned:
        return
    _legacy_warned = True
    _logger.warning(
        "Deprecated config location: reading %s because %s has no such file. "
        "Move the platform configuration to %s (or set %s); the %s fallback "
        "is removed in the next release.",
        old,
        new,
        preferred_platform_config_dir(),
        PLATFORM_CONFIG_DIR_SETTING,
        LEGACY_PLATFORM_APP_DIR,
    )


def platform_config_file(name: str) -> Path:
    """Resolve one platform config file, e.g. ``workspace.yml``.

    Returns the file under :func:`preferred_platform_config_dir` when it exists
    there; otherwise the legacy file when that exists (logging the one-time
    deprecation warning); otherwise the preferred path, for a writer to create.
    """
    preferred = preferred_platform_config_dir() / name
    if preferred.exists():
        return preferred
    legacy = legacy_platform_config_dir() / name
    if legacy.exists():
        _warn_legacy(preferred, legacy)
        return legacy
    return preferred


def platform_config_dir(probe: str = "config.json") -> Path:
    """The platform config directory, chosen by where ``probe`` lives.

    The preferred directory wins unless ``probe`` is absent from it and present
    in the legacy directory, in which case the legacy directory is returned and
    the one-time deprecation warning is logged. The directory is not created.
    """
    return platform_config_file(probe).parent
