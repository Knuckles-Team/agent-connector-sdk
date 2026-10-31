"""Arbora platform configuration directory resolution."""

from __future__ import annotations

import os
from pathlib import Path

# --- Platform (Arbora) configuration directory ---------------------------
#
# Arbora owns the platform configuration location: ``ARBORA_CONFIG_DIR``
# or ``$XDG_CONFIG_HOME/arbora``. There is no fallback to the pre-rename
# locations (hard cutover).

_PLATFORM_CONFIG_DIR_SETTING = "ARBORA_CONFIG_DIR"
_PLATFORM_APP_DIR = "arbora"


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))


def _env_dir(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def preferred_platform_config_dir() -> Path:
    """``ARBORA_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/arbora``."""
    return _env_dir(_PLATFORM_CONFIG_DIR_SETTING) or _config_home() / _PLATFORM_APP_DIR


def platform_config_file(name: str) -> Path:
    """Resolve one platform config file, e.g. ``workspace.yml``.

    Always the path under :func:`preferred_platform_config_dir`; the file may
    not exist yet, for a writer to create.
    """
    return preferred_platform_config_dir() / name


def platform_config_dir(probe: str = "config.json") -> Path:
    """The platform config directory (``probe`` is kept for callers' symmetry).

    The directory is not created.
    """
    return platform_config_file(probe).parent
