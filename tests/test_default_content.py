"""SDK-CONNECTOR-CONTROL-R073: content is passed explicitly; the factory has no implicit lookup."""

from __future__ import annotations

import pytest
from fastmcp import Client

from agent_connector_sdk.connector import content_dirs
from agent_connector_sdk.mcp.content import ConnectorContent
from agent_connector_sdk.mcp.server import create_mcp_server

pytestmark = pytest.mark.spec("SDK-CONNECTOR-CONTROL-R073")

from pathlib import Path  # noqa: E402

FIXTURE = Path(__file__).parent / "fixture_package"


async def _uris(mcp) -> tuple[set[str], set[str]]:
    async with Client(mcp) as client:
        return (
            {str(r.uri) for r in await client.list_resources()},
            {p.name for p in await client.list_prompts()},
        )


async def test_factory_without_content_serves_tools_only() -> None:
    _, mcp, _ = create_mcp_server("x-mcp", version="1", command_args=[])
    uris, prompts = await _uris(mcp)
    assert not any(u.startswith(("skill://", "ontology://", "shapes://")) for u in uris)
    assert prompts == {"connector-status"}


async def test_explicit_content_is_served_under_its_name() -> None:
    content = ConnectorContent(
        connector="other-mcp", package_root=FIXTURE, package_version="1.0.0"
    )
    _, mcp, _ = create_mcp_server(
        "x-mcp", version="1", command_args=[], content=content
    )
    uris, prompts = await _uris(mcp)
    assert any(u.startswith("skill://") for u in uris)
    assert any(u.startswith("ontology://other-mcp/") for u in uris)
    assert any(u.startswith("shapes://other-mcp/") for u in uris)
    assert "demo_agent" in prompts


def test_content_dirs_names_the_conventional_directories() -> None:
    dirs = content_dirs("agent_connector_sdk")
    assert dirs.skills.name == "skills" and dirs.ontology.name == "ontology"
