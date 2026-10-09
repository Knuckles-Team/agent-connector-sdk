"""WebFetchSourceAdapter wired to ports.SourceAdapter: a real fetch per page."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import mcp_types
import pytest

from agent_connector_sdk.adapters.web_fetch import WebFetchSourceAdapter
from agent_connector_sdk.contracts import SEAM_SCHEMA_VERSION
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse

_PAGE_A = b"<html><head><title>Page A</title></head><body>Content A</body></html>"
_PAGE_B = b"<html><head><title>Page B</title></head><body>Content B</body></html>"


class _UnusedSession:
    """An ``McpSession`` this adapter never calls (it fetches HTTP directly)."""

    async def server_identity(self) -> Any:
        raise AssertionError("WebFetchSourceAdapter must not use the session")

    async def list_tools(self) -> Sequence[Any]:
        raise AssertionError("WebFetchSourceAdapter must not use the session")

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        raise AssertionError("WebFetchSourceAdapter must not use the session")

    async def list_prompts(self) -> Sequence[Any]:
        raise AssertionError("WebFetchSourceAdapter must not use the session")

    async def get_prompt(
        self, name: str, arguments: Mapping[str, str]
    ) -> mcp_types.GetPromptResult:
        raise AssertionError("WebFetchSourceAdapter must not use the session")

    async def list_resources(self) -> Sequence[Any]:
        raise AssertionError("WebFetchSourceAdapter must not use the session")

    async def read_resource(self, uri: str) -> str:
        raise AssertionError("WebFetchSourceAdapter must not use the session")


_SESSION = _UnusedSession()


def test_unused_session_satisfies_the_mcp_session_protocol() -> None:
    assert isinstance(_SESSION, McpSession)


def test_describe_declares_pagination_and_the_seam_schema_version() -> None:
    adapter = WebFetchSourceAdapter(
        ("http://example.invalid",), connector="test-connector", mapping_reference="v1"
    )
    descriptor = adapter.describe()

    assert descriptor.kind == adapter.kind == "web_fetch"
    assert descriptor.schema_version == SEAM_SCHEMA_VERSION
    assert descriptor.pagination


async def test_sweeping_two_urls_recovers_from_a_checkpoint() -> None:
    with (
        ScriptedHttpServer(ScriptedResponse(status=200, body=_PAGE_A)) as server_a,
        ScriptedHttpServer(ScriptedResponse(status=200, body=_PAGE_B)) as server_b,
    ):
        adapter = WebFetchSourceAdapter(
            (server_a.base_url, server_b.base_url),
            connector="test-connector",
            mapping_reference="web_fetch.v1",
        )

        descriptor = await adapter.discover(_SESSION)
        assert descriptor.stream == adapter.stream == "web_fetch"
        assert len(descriptor.schema_sha256) == 64

        first = await adapter.extract(_SESSION, None)
        assert not first.exhausted
        assert [r.record_id for r in first.records] == [server_a.base_url]
        assert first.records[0].provenance.source_uri == server_a.base_url
        assert first.records[0].payload["title"] == "Page A"

        second = await adapter.extract(_SESSION, first.checkpoint)
        assert second.exhausted
        assert [r.record_id for r in second.records] == [server_b.base_url]

        # Resuming from the first checkpoint in a fresh call reproduces page two
        # (the scripted server needs a fresh queued response for the re-fetch).
        server_b.enqueue(ScriptedResponse(status=200, body=_PAGE_B))
        resumed = await adapter.extract(_SESSION, first.checkpoint)
        assert resumed.records == second.records
        assert resumed.exhausted

        # A terminal checkpoint yields an empty, still-exhausted page.
        terminal = await adapter.extract(_SESSION, second.checkpoint)
        assert terminal.records == ()
        assert terminal.exhausted

        report = await adapter.reconcile(
            _SESSION, known_ids=frozenset({server_a.base_url})
        )
        assert report.missing_from_source == ()
        assert report.unknown_to_sink == (server_b.base_url,)


@pytest.mark.parametrize("bad_status", [500, 404])
async def test_a_failed_fetch_yields_an_empty_page_not_a_crash(bad_status: int) -> None:
    with ScriptedHttpServer(
        ScriptedResponse(status=bad_status, body=b"nope")
    ) as server:
        adapter = WebFetchSourceAdapter(
            (server.base_url,), connector="test-connector", mapping_reference="v1"
        )
        page = await adapter.extract(_SESSION, None)

    assert page.records == ()
    assert page.exhausted
