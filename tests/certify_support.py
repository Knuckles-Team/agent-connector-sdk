"""Checkouts, live tool listings and server commands for the connector-certify tests."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from fixture_server import PACKAGE_ROOT, build_reader_server

from agent_connector_sdk.certify.pins import render_fingerprints, rewrite_manifest_pins
from agent_connector_sdk.manifest.tool_schema import compatibility_fingerprint
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport

CERTIFY_SERVER = Path(__file__).parent / "certify_server.py"
#: The compatibility fingerprint of ``demo_reader`` as a client lists it.
LIVE = "457e92adf7af7982d12fa41cc79c69b16b7717a57ead15fb4e318b9f1cb045d6"
#: What the agent-utilities certifier pinned: the fingerprint of ``{}``.
EMPTY = compatibility_fingerprint("demo_reader", {})
DRIFTED = "ab" * 32


def checkout_copy(tmp_path: Path, pin: str | None = None) -> Path:
    """A copy of the fixture package, with both pin files set to ``pin``."""
    root = tmp_path / "demo-agent"
    shutil.copytree(PACKAGE_ROOT, root)
    if pin is not None:
        manifest = root / "connector_manifest.yml"
        manifest.write_text(
            rewrite_manifest_pins(manifest.read_text(encoding="utf-8"), {"demo": pin}),
            encoding="utf-8",
        )
        (root / "connectors" / "tool_schema_fingerprints.json").write_text(
            render_fingerprints("demo-agent", {"demo_reader": pin}), encoding="utf-8"
        )
    return root


async def live_tools() -> list[Any]:
    """``tools/list`` of the fixture server, as a client receives it."""
    endpoint = TransportEndpoint(in_process=build_reader_server(with_content=False))
    async with McpTransport().session(endpoint) as session:
        return list(await session.list_tools())


def server_command(*extra: str) -> list[str]:
    """The ``-- COMMAND ...`` tail that serves the fixture over stdio."""
    return ["--", sys.executable, str(CERTIFY_SERVER), *extra]
