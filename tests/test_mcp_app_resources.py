"""MCP Apps resources remain typed MCP resource artifacts."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from agent_connector_sdk.artifacts.pack import build_content_pack
from agent_connector_sdk.artifacts.resources import ResourceArtifactKind
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport

APP_URI = "ui://searxng-mcp/search.html"
APP_HTML = "<!doctype html><html><body><main>SearXNG</main></body></html>"
SERVER = ServerIdentity(name="SearXNGMCP", version="2.3.4")


def _entry(
    *,
    uri: str = APP_URI,
    media_type: str = "text/html",
    body: str = APP_HTML,
    server: ServerIdentity = SERVER,
) -> CapturedArtifact:
    return CapturedArtifact(
        kind="resource",
        uri=uri,
        name="searxng-search",
        media_type=media_type,
        body=body,
        server=server,
    )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R073")
async def test_mcp_app_resource_is_captured_by_the_existing_pack_path() -> None:
    """A real in-process MCP resource survives listing and pack capture."""
    mcp = FastMCP(SERVER.name, version=SERVER.version)

    @mcp.resource(
        uri=APP_URI,
        name="searxng-search",
        mime_type="text/html",
    )
    def search_app() -> str:
        return APP_HTML

    async with McpTransport().session(TransportEndpoint(in_process=mcp)) as session:
        entries = await ResourceArtifactKind().list_entries(
            session, await session.server_identity()
        )
        pack = await build_content_pack(
            session,
            connector="searxng-mcp",
            kinds=(ResourceArtifactKind(),),
        )

    entry = next(item for item in entries if item.uri == APP_URI)
    assert entry.kind == "resource"
    assert entry.media_type == "text/html"
    assert entry.body == APP_HTML
    assert entry.server == SERVER
    ResourceArtifactKind().validate(entry)
    assert pack.resource_uris == {APP_URI}
    app_entries = [item for item in pack.archive.entries if item.uri == APP_URI]
    assert len(app_entries) == 1
    assert app_entries[0].kind.value == "resource"
    assert app_entries[0].output_schema is None


@pytest.mark.parametrize(
    ("uri", "media_type"),
    (
        ("https://internal.example/app.html", "text/html"),
        (APP_URI, "application/json"),
    ),
)
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R073")
def test_mcp_app_resource_rejects_unknown_uri_or_type(
    uri: str, media_type: str
) -> None:
    with pytest.raises(MalformedArtifactError):
        ResourceArtifactKind().validate(_entry(uri=uri, media_type=media_type))


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R073")
def test_mcp_app_resource_rejects_missing_server_provenance() -> None:
    malformed = _entry().model_copy(update={"server": None})
    with pytest.raises(MalformedArtifactError, match="provenance"):
        ResourceArtifactKind().validate(malformed)


@pytest.mark.parametrize("media_type", ("text/html", "text/html;profile=mcp-app"))
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R073")
def test_mcp_app_resource_accepts_both_standard_html_media_types(
    media_type: str,
) -> None:
    ResourceArtifactKind().validate(_entry(media_type=media_type))


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R073")
def test_mcp_app_resource_rejects_a_non_resource_artifact_type() -> None:
    malformed = _entry().model_copy(update={"kind": "mcp-app"})
    with pytest.raises(MalformedArtifactError):
        ResourceArtifactKind().validate(malformed)
