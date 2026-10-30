"""Console entry for a declared connector.

``[project.scripts] <fleet-name> = "agent_connector_sdk.cli:serve"`` serves the
connector whose fleet name is the script's name; with one installed connector
the name is optional (SCION-CONNECTOR-CONTROL-R019.1).
"""

from __future__ import annotations

import sys
from pathlib import Path

from agent_connector_sdk.connector import installed_connectors, run

__all__ = ["serve"]


def serve() -> None:
    """Serve the installed connector named by ``argv[0]`` (or the only one)."""
    connectors = installed_connectors()
    script = Path(sys.argv[0]).name
    named = [c for c in connectors if c.name == script]
    chosen = named or (connectors if len(connectors) == 1 else [])
    if len(chosen) != 1:
        names = ", ".join(c.name for c in connectors) or "none"
        raise SystemExit(f"no unique connector for {script!r}; installed: {names}")
    run(chosen[0].package)
