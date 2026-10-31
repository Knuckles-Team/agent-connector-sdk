"""Live source declaration for :mod:`scion_sdk.mcp.tool_surface`."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _package_root(owner: Any) -> Path | None:
    """The directory of the top-level package that defines ``owner``."""
    module_name = getattr(owner, "__module__", None) or getattr(owner, "__name__", "")
    top = str(module_name).split(".", 1)[0]
    module = sys.modules.get(top)
    location = getattr(module, "__file__", None)
    return Path(location).parent if location else None


def _declared_connector(root: Path, fallback: str) -> str:
    from scion_sdk.connector_identity import (
        ConnectorIdentityError,
        connector_name,
    )

    try:
        return connector_name(root.name)
    except ConnectorIdentityError:
        return fallback


def _register_declared_sources(mcp: Any, prefix: str, root: Path | None) -> None:
    """Serve the connector's live source declaration (SCION-CONNECTOR-CONTROL-R075).

    ``connector://resources`` is built from the read tools' ``meta``.
    """
    if root is None:
        return
    from scion_sdk.ingest.live_declaration import (
        load_sources_module,
        register_live_declaration,
    )

    register_live_declaration(
        mcp,
        _declared_connector(root, prefix),
        declared=load_sources_module(root),
    )
