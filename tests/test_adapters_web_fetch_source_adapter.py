"""WebFetchSourceAdapter wired to ports.SourceAdapter: a real fetch per page."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any

import mcp_types
import pytest
from epistemic_graph.generated.source_ingestion import SourceCheckpoint

from agent_connector_sdk.adapters.web_fetch import WebFetchSourceAdapter
from agent_connector_sdk.contracts import SEAM_SCHEMA_VERSION
from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
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


@pytest.mark.spec("SCION-SOURCE-INGEST-R005")
def test_describe_declares_pagination_and_the_seam_schema_version() -> None:
    adapter = WebFetchSourceAdapter(
        ("http://example.invalid",), connector="test-connector", mapping_reference="v1"
    )
    descriptor = adapter.describe()

    assert descriptor.kind == adapter.kind == "web_fetch"
    assert descriptor.schema_version == SEAM_SCHEMA_VERSION
    assert descriptor.pagination


@pytest.mark.spec("SCION-SOURCE-INGEST-R005")
async def test_sweeping_two_urls_recovers_from_a_checkpoint() -> None:
    with (
        ScriptedHttpServer(ScriptedResponse(status=200, body=_PAGE_A)) as server_a,
        ScriptedHttpServer(ScriptedResponse(status=200, body=_PAGE_B)) as server_b,
    ):
        adapter = WebFetchSourceAdapter(
            (server_a.base_url, server_b.base_url),
            connector="test-connector",
            mapping_reference="web_fetch.v1",
            allowed_private_hosts=("127.0.0.1",),
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
async def test_a_failed_fetch_refuses_the_page(bad_status: int) -> None:
    with ScriptedHttpServer(
        ScriptedResponse(status=bad_status, body=b"nope")
    ) as server:
        adapter = WebFetchSourceAdapter(
            (server.base_url,),
            connector="test-connector",
            mapping_reference="v1",
            allowed_private_hosts=("127.0.0.1",),
        )
        with pytest.raises(SourceContractError, match="web fetch failed"):
            await adapter.extract(_SESSION, None)


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.41")
async def test_failed_fetch_preserves_accepted_checkpoint() -> None:
    checkpoint = SourceCheckpoint(stream="web_fetch", position={"index": 1})

    class Sink:
        async def source_status(self, connector: str, stream: str) -> Any:
            return SimpleNamespace(accepted_checkpoint=checkpoint)

        async def submit(self, request: Any) -> Any:
            raise AssertionError("a failed fetch must not be submitted")

    with ScriptedHttpServer(
        ScriptedResponse(status=503, body=b"unavailable")
    ) as server:
        adapter = WebFetchSourceAdapter(
            (server.base_url + "/first", server.base_url + "/second"),
            connector="test-connector",
            mapping_reference="v1",
            allowed_private_hosts=("127.0.0.1",),
        )
        target = SyncTarget(connector="test-connector", sink=Sink(), max_pages=2)  # type: ignore[arg-type]
        with pytest.raises(SourceContractError, match="web fetch failed"):
            await sync_stream(_SESSION, adapter, target)
    assert checkpoint.position == {"index": 1}


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.42")
async def test_blocked_web_fetch_never_submits_or_advances_checkpoint() -> None:
    checkpoint = SourceCheckpoint(stream="web_fetch", position={"index": 1})

    class Sink:
        async def source_status(self, connector: str, stream: str) -> Any:
            return SimpleNamespace(accepted_checkpoint=checkpoint)

        async def submit(self, request: Any) -> Any:
            raise AssertionError("a blocked fetch must not be submitted")

    with ScriptedHttpServer(ScriptedResponse(body=_PAGE_A)) as server:
        adapter = WebFetchSourceAdapter(
            (server.base_url + "/first", server.base_url + "/second"),
            connector="test-connector",
            mapping_reference="v1",
        )
        target = SyncTarget(connector="test-connector", sink=Sink(), max_pages=2)  # type: ignore[arg-type]
        with pytest.raises(SourceContractError, match="web fetch failed"):
            await sync_stream(_SESSION, adapter, target)
        assert server.requests == []
    assert checkpoint.position == {"index": 1}


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.49")
async def test_invalid_checkpoint_refuses_before_fetch(monkeypatch) -> None:
    from agent_connector_sdk.adapters import web_fetch

    calls = []

    async def fetch(*args, **kwargs):
        calls.append(args)
        raise AssertionError("invalid or terminal checkpoints must not fetch")

    monkeypatch.setattr(web_fetch, "fetch_page", fetch)
    adapter = WebFetchSourceAdapter(
        ("https://example.invalid/one",), connector="test", mapping_reference="v1"
    )
    for stream, position in (
        ("other", {"index": 0}),
        ("web_fetch", {}),
        ("web_fetch", {"index": -1}),
        ("web_fetch", {"index": 2}),
        ("web_fetch", {"index": True}),
        ("web_fetch", {"index": "0"}),
        ("web_fetch", {"index": 0.5}),
    ):
        with pytest.raises(SourceContractError, match="invalid web fetch checkpoint"):
            await adapter.extract(
                _SESSION, SourceCheckpoint(stream=stream, position=position)
            )
    terminal = SourceCheckpoint(stream="web_fetch", position={"index": 1})
    first = await adapter.extract(_SESSION, terminal)
    second = await adapter.extract(_SESSION, first.checkpoint)
    assert first.exhausted and second.exhausted
    assert first.checkpoint == terminal == second.checkpoint
    assert calls == []


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.50")
async def test_checkpoint_binds_ordered_url_list(monkeypatch) -> None:
    from agent_connector_sdk.adapters import web_fetch

    calls = []

    async def fetch(url, **_kwargs):
        calls.append(url)
        return web_fetch.FetchedPage(url=url, markdown="page")

    monkeypatch.setattr(web_fetch, "fetch_page", fetch)
    urls = ("https://example.invalid/one", "https://example.invalid/two")
    adapter = WebFetchSourceAdapter(urls, connector="test", mapping_reference="v1")
    first = await adapter.extract(_SESSION, None)
    assert len(first.checkpoint.position["url_list_sha256"]) == 64
    resumed = await adapter.extract(_SESSION, first.checkpoint)
    assert resumed.exhausted and calls == list(urls)
    changed = WebFetchSourceAdapter(
        tuple(reversed(urls)), connector="test", mapping_reference="v1"
    )
    with pytest.raises(SourceContractError, match="does not match URL list"):
        await changed.extract(_SESSION, first.checkpoint)
    assert calls == list(urls)
    legacy = SourceCheckpoint(stream="web_fetch", position={"index": 1})
    upgraded = await adapter.extract(_SESSION, legacy)
    assert (
        upgraded.checkpoint.position["url_list_sha256"]
        == first.checkpoint.position["url_list_sha256"]
    )


@pytest.mark.timeout(30)
@pytest.mark.spec("SCION-SOURCE-INGEST-R005.54")
async def test_legacy_fetch_handles_adversarial_html() -> None:
    body = ("<meta " * 50_000 + "<title>" * 50_000 + "<" * 100_000).encode()
    with ScriptedHttpServer(
        ScriptedResponse(body=body, headers={"Content-Type": "text/html"})
    ) as server:
        adapter = WebFetchSourceAdapter(
            (server.base_url,),
            connector="test",
            mapping_reference="v1",
            allowed_private_hosts=("127.0.0.1",),
        )
        page = await adapter.extract(_SESSION, None)
        assert page.exhausted and len(page.records) == 1
        assert page.records[0].payload["markdown"]
        assert server.requests[0].headers["accept-encoding"] == "identity"
