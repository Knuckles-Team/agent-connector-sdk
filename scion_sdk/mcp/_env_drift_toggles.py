"""``register_<tag>_tools`` toggle variables for :mod:`scion_sdk.mcp.env_drift`."""

from __future__ import annotations

import re
from pathlib import Path

from scion_sdk.mcp._env_drift_scan import _walk_files

_REGISTRAR = re.compile(r"(?<![0-9A-Za-z_])register_([a-z][a-z0-9_]*?)_tools\b")


def _derive_toggle_vars(root: Path) -> set[str]:
    """``register_<tag>_tools`` in production code -> ``<TAG>TOOL``."""
    tags: set[str] = set()
    for py in _walk_files(root, suffix=".py"):
        if "tests" in py.parts or "test" in py.parts:
            continue
        try:
            tags.update(_REGISTRAR.findall(py.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    tags -= {"verbose", "tool_surface", "conditional"}
    return {f"{tag.upper()}TOOL" for tag in tags}
