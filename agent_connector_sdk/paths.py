"""Per-connector state directories (SDK-CONNECTOR-CONTROL-R014.7).

Replaces agent-utilities ``core.paths`` for connectors: XDG locations under an
``agent-connectors`` application directory, each overridable by one setting.
No harness paths (skills, prompts, KG databases) live here.

:func:`platform_config_dir` / :func:`platform_config_file` resolve the shared
Arbora platform configuration (``workspace.yml``, ``config.json``, ...).
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
    "legacy_platform_config_dirs",
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


# --- Platform (Arbora) configuration directory ---------------------------
#
# Arbora owns the platform configuration location: ``ARBORA_CONFIG_DIR``
# or ``$XDG_CONFIG_HOME/arbora``. For one release, a file that is absent
# there is read from the legacy locations, in order: the pre-rename graph-os
# location (``GRAPH_OS_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/graph-os``), then
# the agent-utilities location (``AGENT_UTILITIES_CONFIG_DIR`` or
# ``$XDG_CONFIG_HOME/agent-utilities``), and a single deprecation warning
# names both paths. An explicit legacy setting with no ``ARBORA_CONFIG_DIR``
# is still honoured as the directory (with the same warning) for that release.

PLATFORM_CONFIG_DIR_SETTING = "ARBORA_CONFIG_DIR"
LEGACY_PLATFORM_CONFIG_DIR_SETTINGS = (
    "GRAPH_OS_CONFIG_DIR",
    "AGENT_UTILITIES_CONFIG_DIR",
)
LEGACY_PLATFORM_APP_DIRS = ("graph-os", "agent-utilities")
LEGACY_PLATFORM_CONFIG_DIR_SETTING = LEGACY_PLATFORM_CONFIG_DIR_SETTINGS[-1]
PLATFORM_APP_DIR = "arbora"
LEGACY_PLATFORM_APP_DIR = LEGACY_PLATFORM_APP_DIRS[-1]

_platform_logger = logging.getLogger(__name__)
_legacy_warned = False


def _config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config").parent


def _env_dir(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def preferred_platform_config_dir() -> Path:
    """``ARBORA_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/arbora`` (no fallback)."""
    return _env_dir(PLATFORM_CONFIG_DIR_SETTING) or _config_home() / PLATFORM_APP_DIR


def legacy_platform_config_dirs() -> tuple[Path, ...]:
    """The legacy directories in fallback order (graph-os, then agent-utilities)."""
    return tuple(
        _env_dir(setting_name) or _config_home() / app_dir
        for setting_name, app_dir in zip(
            LEGACY_PLATFORM_CONFIG_DIR_SETTINGS, LEGACY_PLATFORM_APP_DIRS, strict=True
        )
    )


def legacy_platform_config_dir() -> Path:
    """``AGENT_UTILITIES_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/agent-utilities``."""
    return legacy_platform_config_dirs()[-1]


def _warn_legacy(legacy: Path) -> None:
    global _legacy_warned
    if _legacy_warned:
        return
    _legacy_warned = True
    _platform_logger.warning(
        "Deprecated config location %s is in use; move the platform "
        "configuration to %s (or set %s). The graph-os and agent-utilities "
        "fallbacks are removed in the next release.",
        legacy,
        preferred_platform_config_dir(),
        PLATFORM_CONFIG_DIR_SETTING,
    )


def platform_config_file(name: str) -> Path:
    """Resolve one platform config file, e.g. ``workspace.yml``.

    Returns the file under :func:`preferred_platform_config_dir` when it exists
    there; otherwise the first legacy file that exists (logging the one-time
    deprecation warning); otherwise the preferred path, for a writer to create.
    An explicit legacy ``GRAPH_OS_CONFIG_DIR`` or ``AGENT_UTILITIES_CONFIG_DIR``
    without ``ARBORA_CONFIG_DIR`` resolves inside that directory.
    """
    if not _env_dir(PLATFORM_CONFIG_DIR_SETTING):
        for setting_name in LEGACY_PLATFORM_CONFIG_DIR_SETTINGS:
            explicit_legacy = _env_dir(setting_name)
            if explicit_legacy:
                _warn_legacy(explicit_legacy)
                return explicit_legacy / name
    preferred = preferred_platform_config_dir() / name
    if preferred.exists():
        return preferred
    for legacy_dir in legacy_platform_config_dirs():
        legacy = legacy_dir / name
        if legacy.exists():
            _warn_legacy(legacy)
            return legacy
    return preferred


def platform_config_dir(probe: str = "config.json") -> Path:
    """The platform config directory, chosen by where ``probe`` lives.

    The preferred directory wins unless ``probe`` is absent from it and present
    in the legacy directory, in which case the legacy directory is returned and
    the one-time deprecation warning is logged. The directory is not created.
    """
    return platform_config_file(probe).parent
