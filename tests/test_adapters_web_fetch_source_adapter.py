"""WebFetchSourceAdapter calls a connector's ``web_extract`` tool per page."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from epistemic_graph.generated.source_ingestion import SourceCheckpoint
from fastmcp import Client, FastMCP

from agent_connector_sdk.adapters.web_fetch import (
    WebFetchRefusalError,
    WebFetchSourceAdapter,
    WebQueryRef,
)
from agent_connector_sdk.contracts import SEAM_SCHEMA_VERSION
from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.ports.web_source import (
    WebFetchRequest,
    WebPageResult,
    WebSourceRefused,
    content_digest,
    register_web_source_tools,
)
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream


@dataclass
class _Source:
    """A scripted connector: refuses URLs listed in ``refuse``."""

    backend: str = "fixture"
    refuse: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def fetch(self, request: WebFetchRequest) -> WebPageResult:
        return await self.extract(request)

    async def extract(self, request: WebFetchRequest) -> WebPageResult:
        self.calls.append(request.url)
        if request.url in self.refuse:
            raise WebSourceRefused(self.refuse[request.url], "scripted")
        text = f"# Content of {request.url}"
        return WebPageResult(
            url=request.url,
            canonical_url=request.url + "/canonical",
            final_url=request.url,
            status=200,
            content_type="text/html",
            byte_count=len(text),
            content_digest=content_digest(text),
            retrieved_at="2026-10-30T00:00:00+00:00",
            title="T",
            text_markdown=text,
            backend=self.backend,
        )


class _Session:
    """An ``McpSession`` over a connected FastMCP client (only what is needed)."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self.tool_calls: list[str] = []

    async def list_tools(self) -> Sequence[Any]:
        return await self._client.list_tools()

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        self.tool_calls.append(name)
        result = await self._client.call_tool(
            name, dict(arguments), raise_on_error=False
        )
        return result.structured_content


@asynccontextmanager
async def _served(
    source: _Source | None, *, tools: bool = True
) -> AsyncIterator[_Session]:
    server = FastMCP("fixture-web-source")
    if tools and source is not None:
        register_web_source_tools(server, source)
    else:

        @server.tool()
        def unrelated() -> str:
            return "x"

    async with Client(server) as client:
        yield _Session(client)


def _adapter(*urls: str, **kwargs: Any) -> WebFetchSourceAdapter:
    return WebFetchSourceAdapter(
        urls, connector="test-connector", mapping_reference="web_fetch.v1", **kwargs
    )


URL_A = "https://a.example/page"
URL_B = "https://b.example/page"


@pytest.mark.spec("SCION-SOURCE-INGEST-R005")
def test_describe_declares_pagination_and_the_seam_schema_version() -> None:
    descriptor = _adapter(URL_A).describe()
    assert descriptor.kind == "web_fetch"
    assert descriptor.schema_version == SEAM_SCHEMA_VERSION
    assert descriptor.pagination


@pytest.mark.spec("SCION-SOURCE-INGEST-R005")
async def test_sweeping_two_urls_recovers_from_a_checkpoint() -> None:
    source = _Source()
    async with _served(source) as session:
        adapter = _adapter(URL_A, URL_B)
        descriptor = await adapter.discover(session)
        assert descriptor.stream == "web_fetch" and descriptor.tool == "web_extract"
        assert len(descriptor.schema_sha256) == 64

        first = await adapter.extract(session, None)
        assert not first.exhausted
        assert [r.record_id for r in first.records] == [URL_A]
        second = await adapter.extract(session, first.checkpoint)
        assert second.exhausted and [r.record_id for r in second.records] == [URL_B]
        resumed = await adapter.extract(session, first.checkpoint)
        assert resumed.records == second.records
        terminal = await adapter.extract(session, second.checkpoint)
        assert terminal.records == () and terminal.exhausted

        report = await adapter.reconcile(session, known_ids=frozenset({URL_A}))
        assert report.missing_from_source == ()
        assert report.unknown_to_sink == (URL_B,)


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.40.3")
async def test_extract_calls_connector_tool() -> None:
    source = _Source()
    async with _served(source) as session:
        page = await _adapter(URL_A).extract(session, None)
    assert source.calls == [URL_A]
    assert session.tool_calls == ["web_extract"]
    assert page.records[0].provenance.tool == "web_extract"
    assert page.records[0].provenance.server == "fixture"


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.40.4")
async def test_refusal_keeps_checkpoint() -> None:
    checkpoint = SourceCheckpoint(stream="web_fetch", position={"index": 1})

    class Sink:
        async def source_status(self, connector: str, stream: str) -> Any:
            return SimpleNamespace(accepted_checkpoint=checkpoint)

        async def submit(self, request: Any) -> Any:
            raise AssertionError("a refused page must not be submitted")

    source = _Source(refuse={URL_B: "robots_disallowed"})
    async with _served(source) as session:
        adapter = _adapter(URL_A, URL_B)
        target = SyncTarget(connector="test-connector", sink=Sink(), max_pages=2)  # type: ignore[arg-type]
        with pytest.raises(WebFetchRefusalError) as refused:
            await sync_stream(session, adapter, target)
    assert refused.value.reason == "robots_disallowed"
    assert refused.value.refusal is not None
    assert checkpoint.position == {"index": 1}


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.40.4")
async def test_uncertified_connector_is_refused_before_any_call() -> None:
    async with _served(None, tools=False) as session:
        adapter = _adapter(URL_A)
        with pytest.raises(WebFetchRefusalError) as refused:
            await adapter.extract(session, None)
        with pytest.raises(WebFetchRefusalError):
            await adapter.discover(session)
    assert refused.value.reason == "contract_uncertified"
    assert session.tool_calls == []


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.40.4")
async def test_tampered_digest_and_empty_page_are_refused() -> None:
    class Tampered(_Source):
        async def extract(self, request: WebFetchRequest) -> WebPageResult:
            page = await super().extract(request)
            return page.model_copy(update={"text_markdown": "   "})

    async with _served(Tampered()) as session:
        # The served tool refuses the digest mismatch; the adapter surfaces it.
        with pytest.raises(WebFetchRefusalError) as refused:
            await _adapter(URL_A).extract(session, None)
    assert refused.value.reason == "upstream_failed"


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.40.5")
async def test_record_provenance_matches_engine_model() -> None:
    source = _Source(backend="archive")
    query = WebQueryRef(text="graph databases", rank=3)
    async with _served(source) as session:
        adapter = _adapter(URL_A, URL_B, queries={URL_A: query})
        first = await adapter.extract(session, None)
        second = await adapter.extract(session, first.checkpoint)
    payload = first.records[0].payload
    assert payload["url"] == URL_A
    assert payload["canonical_url"] == URL_A + "/canonical"
    assert payload["retrieved_at"] == "2026-10-30T00:00:00+00:00"
    assert payload["content_digest"] == content_digest(payload["text_markdown"])
    assert payload["backend"] == "archive"
    assert payload["query_text"] == "graph databases" and payload["rank"] == 3
    assert payload["query_digest"] == content_digest("graph databases")
    assert "query_text" not in second.records[0].payload


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.49")
async def test_invalid_checkpoint_refuses_before_fetch() -> None:
    source = _Source()
    async with _served(source) as session:
        adapter = _adapter("https://example.invalid/one")
        for stream, position in (
            ("other", {"index": 0}),
            ("web_fetch", {}),
            ("web_fetch", {"index": -1}),
            ("web_fetch", {"index": 2}),
            ("web_fetch", {"index": True}),
            ("web_fetch", {"index": "0"}),
            ("web_fetch", {"index": 0.5}),
        ):
            with pytest.raises(
                SourceContractError, match="invalid web fetch checkpoint"
            ):
                await adapter.extract(
                    session, SourceCheckpoint(stream=stream, position=position)
                )
        terminal = SourceCheckpoint(stream="web_fetch", position={"index": 1})
        first = await adapter.extract(session, terminal)
        second = await adapter.extract(session, first.checkpoint)
    assert first.exhausted and second.exhausted
    assert first.checkpoint == terminal == second.checkpoint
    assert source.calls == []


@pytest.mark.spec("SCION-SOURCE-INGEST-R005.50")
async def test_checkpoint_binds_ordered_url_list() -> None:
    source = _Source()
    urls = ("https://example.invalid/one", "https://example.invalid/two")
    async with _served(source) as session:
        adapter = _adapter(*urls)
        first = await adapter.extract(session, None)
        assert len(first.checkpoint.position["url_list_sha256"]) == 64
        resumed = await adapter.extract(session, first.checkpoint)
        assert resumed.exhausted and source.calls == list(urls)
        changed = _adapter(*reversed(urls))
        with pytest.raises(SourceContractError, match="does not match URL list"):
            await changed.extract(session, first.checkpoint)
        assert source.calls == list(urls)
        legacy = SourceCheckpoint(stream="web_fetch", position={"index": 1})
        upgraded = await adapter.extract(session, legacy)
    assert (
        upgraded.checkpoint.position["url_list_sha256"]
        == first.checkpoint.position["url_list_sha256"]
    )
