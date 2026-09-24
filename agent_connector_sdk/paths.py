"""Per-connector XDG directories.

``data_dir("audio-transcriber")`` is ``$XDG_DATA_HOME/audio-transcriber``
(``~/.local/share`` when unset), overridable with ``AUDIO_TRANSCRIBER_DATA_DIR``;
``config_dir`` and ``cache_dir`` follow the same rule with ``XDG_CONFIG_HOME``
(``~/.config``) and ``XDG_CACHE_HOME`` (``~/.cache``). Directories are returned,
not created.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_connector_sdk.config import setting

__all__ = ["cache_dir", "config_dir", "data_dir"]

_BASES = {
    "CONFIG": ("XDG_CONFIG_HOME", ".config"),
    "DATA": ("XDG_DATA_HOME", ".local/share"),
    "CACHE": ("XDG_CACHE_HOME", ".cache"),
}


def _directory(connector: str, kind: str) -> Path:
    name = connector.strip()
    if not name or "/" in name or name in {".", ".."}:
        raise ValueError("connector must be a plain directory name")
    prefix = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    override = setting(f"{prefix}_{kind}_DIR")
    if override:
        return Path(override).expanduser()
    variable, fallback = _BASES[kind]
    return Path(setting(variable) or Path.home() / fallback) / name


def config_dir(connector: str) -> Path:
    """The connector's configuration directory."""
    return _directory(connector, "CONFIG")


def data_dir(connector: str) -> Path:
    """The connector's data directory."""
    return _directory(connector, "DATA")


def cache_dir(connector: str) -> Path:
    """The connector's cache directory."""
    return _directory(connector, "CACHE")
