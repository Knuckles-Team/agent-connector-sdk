"""The requests-floor web-fetch backend: one URL fetched as markdown.

Ported from ``agent_utilities.knowledge_graph.ingestion.web_fetch``
(SCION-SOURCE-INGEST-R005) onto this SDK's own governed HTTP client
(:mod:`agent_connector_sdk.http.client`) instead of agent-utilities' bespoke
HTTP policy, since agent-utilities is not a dependency of this package.

This module ports only the zero-dependency ``requests`` floor: the HTTP GET,
Open Graph/Twitter Card metadata extraction, and markdown normalization. The
ArchiveBox and crawl4ai backends stay in agent-utilities for now (they call
back into agent-utilities-owned infrastructure: the MCP tool fleet and the
skill-graph crawler subprocess); both remain as open lines in
``specs/SCION-SOURCE-INGEST/tasks.md``.

:class:`WebFetchSourceAdapter` sweeps a fixed, ordered list of URLs through a
connector's ``web_extract`` tool (SCION-SOURCE-INGEST-R005.40.3), one URL per
extracted page, so the generated SourceIngest client reaches it through the same
``discover``/``extract``/``reconcile`` surface every other adapter uses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import anyio
import httpx
from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceRecord,
    SourceRecordProvenance,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_connector_sdk.adapters.web_fetch_checkpoint import (
    _next_checkpoint,
    _page_index,
)
from agent_connector_sdk.adapters.web_fetch_helpers import (
    _markdown_from_html,
    extract_og_metadata,
)
from agent_connector_sdk.adapters.web_html_text import _title_from_html
from agent_connector_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from agent_connector_sdk.http.bodies import DEFAULT_MAX_RESPONSE_BYTES, aread_bounded
from agent_connector_sdk.http.client import create_async_http_client
from agent_connector_sdk.http.errors import ResponseTooLargeError
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.ports.web_source import (
    WebFetchRefusal,
    WebFetchRequest,
    WebPageResult,
    content_digest,
)

__all__ = [
    "FetchedPage",
    "WebFetchRefusalError",
    "WebFetchSourceAdapter",
    "WebQueryRef",
    "extract_og_metadata",
    "fetch_page",
]

#: A stable, versioned identity for this adapter's fixed (non-tool) schema.
_SCHEMA_SHA256 = hashlib.sha256(
    b"agent_connector_sdk.adapters.web_fetch/v1"
).hexdigest()

# Browser-like UA — the bare ``httpx`` agent is 403'd by many sites.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class FetchedPage(BaseModel):
    """One fetched web page normalized to markdown/text, with provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    markdown: str
    title: str = ""
    backend: str = "requests"
    description: str = ""
    image: str = ""
    site_name: str = ""


async def fetch_page(
    url: str,
    *,
    timeout: float = 30.0,
    allowed_private_hosts: Sequence[str] = (),
    allow_plaintext: bool = False,
) -> FetchedPage | None:
    """Fetch ``url`` as markdown through the governed HTTP client.

    Returns ``None`` on a non-2xx response or empty content; a caller treats
    that as an unreachable source rather than a fabricated empty page.
    Private hosts need an explicit allowlist. Plaintext to a non-loopback host
    also needs ``allow_plaintext``; it is not implied by the allowlist.
    """
    options = HttpClientOptions(
        base_url=url,
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"},
        pin_egress=True,
        allowed_private_hosts=tuple(allowed_private_hosts),
        allow_plaintext=allow_plaintext,
    )
    try:
        with anyio.fail_after(timeout):
            raw = await _read_web_text(options)
    except (httpx.HTTPError, ResponseTooLargeError, TimeoutError):
        return None
    if raw is None:
        return None
    text = _markdown_from_html(raw)
    if not text.strip():
        return None
    og = extract_og_metadata(raw)
    title = og["title"] or _title_from_html(raw)
    return FetchedPage(
        url=url,
        markdown=text,
        title=title[:200],
        description=og["description"][:500],
        image=og["image"],
        site_name=og["site_name"],
    )


async def _read_web_text(options: HttpClientOptions) -> str | None:
    """Read one identity-encoded response within the shared byte bound."""
    async with (
        create_async_http_client(options) as client,
        client.stream("GET", "") as response,
    ):
        if response.status_code >= 400:
            return None
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            return None
        body = await aread_bounded(response, DEFAULT_MAX_RESPONSE_BYTES)
        return body.decode(response.encoding or "utf-8", errors="replace")


class WebFetchRefusalError(SourceContractError):
    """A connector refused a page (or lacks the certified web-source contract).

    ``reason`` is one of the closed web-source refusal reasons, or
    ``contract_uncertified`` when the connector does not serve the contract.
    ``refusal`` holds the connector's typed refusal when it sent one.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        self.refusal: WebFetchRefusal | None = None
        super().__init__(
            f"web fetch refused: {reason}: {detail}"
            if detail
            else (f"web fetch refused: {reason}")
        )


#: The per-operation tools a connector must serve to be a web source.
_CONTRACT_TOOLS = ("web_fetch", "web_extract")


def _tool_field(tool: Any, name: str) -> Any:
    if isinstance(tool, Mapping):
        return tool.get(name)
    return getattr(tool, name, None)


def _certified_schema_sha256(tools: Sequence[Any]) -> str:
    """Digest of the served ``web_extract`` input schema, or refuse."""
    served = {str(_tool_field(tool, "name")): tool for tool in tools}
    missing = [name for name in _CONTRACT_TOOLS if name not in served]
    if missing:
        raise WebFetchRefusalError(
            "contract_uncertified", f"connector does not serve {', '.join(missing)}"
        )
    schema = _tool_field(served["web_extract"], "input_schema")
    if schema is None:
        schema = _tool_field(served["web_extract"], "inputSchema")
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decoded(result: Any) -> Mapping[str, Any]:
    body = result
    structured = _tool_field(body, "structured_content")
    if structured is not None and not isinstance(body, Mapping):
        body = structured
    if isinstance(body, Mapping) and set(body) == {"result"}:
        body = body["result"]
    if not isinstance(body, Mapping):
        raise SourceContractError("web_extract returned a malformed result")
    return body


def _page_from_result(result: Any) -> WebPageResult:
    body = _decoded(result)
    if body.get("kind") == "refusal":
        try:
            refusal = WebFetchRefusal.model_validate(body)
        except ValidationError as exc:
            raise SourceContractError(
                "web_extract returned a malformed refusal"
            ) from exc
        error = WebFetchRefusalError(refusal.reason, refusal.detail)
        error.refusal = refusal
        raise error
    try:
        page = WebPageResult.model_validate(body)
    except ValidationError as exc:
        raise SourceContractError("web_extract returned a malformed page") from exc
    if not page.text_markdown.strip():
        raise WebFetchRefusalError("extract_empty", "page has no content")
    if page.content_digest != content_digest(page.text_markdown):
        raise WebFetchRefusalError(
            "upstream_failed", "content_digest does not match the text"
        )
    return page


def _record_from_page(
    page: WebPageResult,
    *,
    stream: str,
    connector: str,
    mapping_reference: str,
    schema_sha256: str,
    query: WebQueryRef | None,
) -> SourceRecord:
    payload = page.model_dump(mode="json")
    if query is not None:
        payload["query_text"] = query.text
        payload["query_digest"] = hashlib.sha256(query.text.encode("utf-8")).hexdigest()
        payload["rank"] = query.rank
    return SourceRecord(
        stream=stream,
        record_id=page.url,
        payload=payload,
        mapping_reference=mapping_reference,
        provenance=SourceRecordProvenance(
            adapter_kind=WebFetchSourceAdapter.kind,
            connector=connector,
            server=page.backend,
            source_uri=page.url,
            tool="web_extract",
            tool_schema_sha256=schema_sha256,
        ),
    )


@dataclass(frozen=True)
class WebQueryRef:
    """The search query and rank a page job names, carried into the record."""

    text: str
    rank: int


class WebFetchSourceAdapter:
    """Sweep a fixed, ordered list of URLs through a connector's ``web_extract``.

    The connector serves the web-source contract
    (:mod:`agent_connector_sdk.ports.web_source`); this adapter makes no HTTP
    request itself. One ``web_extract`` call is made per extracted page. A
    connector without both contract tools is refused as ``contract_uncertified``,
    and a refused page raises :class:`WebFetchRefusalError` without advancing
    the checkpoint.
    """

    kind = "web_fetch"

    def __init__(
        self,
        urls: Sequence[str],
        *,
        connector: str,
        mapping_reference: str,
        queries: Mapping[str, WebQueryRef] | None = None,
    ) -> None:
        self._urls = tuple(urls)
        encoded_urls = json.dumps(
            self._urls, ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        self._url_digest = hashlib.sha256(encoded_urls).hexdigest()
        self._connector = connector
        self._mapping_reference = mapping_reference
        self._queries = dict(queries or {})

    @property
    def stream(self) -> str:
        return self.kind

    def describe(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            kind=self.kind,
            pagination=("sequential",),
            incremental=False,
            certified_for_ingestion=True,
        )

    async def discover(self, session: McpSession) -> StreamDescriptor:
        """Declare the stream after verifying the connector's web-source tools."""
        digest = _certified_schema_sha256(await session.list_tools())
        return StreamDescriptor(
            stream=self.stream, tool="web_extract", schema_sha256=digest
        )

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        """Call ``web_extract`` for the next URL in this adapter's list."""
        index = _page_index(
            checkpoint, self.stream, count=len(self._urls), url_digest=self._url_digest
        )
        records: tuple[SourceRecord, ...] = ()
        if index < len(self._urls):
            url = self._urls[index]
            schema_sha256 = _certified_schema_sha256(await session.list_tools())
            request = WebFetchRequest(url=url)
            result = await session.call_tool(
                "web_extract", {"request": request.model_dump(mode="json")}
            )
            records = (
                _record_from_page(
                    _page_from_result(result),
                    stream=self.stream,
                    connector=self._connector,
                    mapping_reference=self._mapping_reference,
                    schema_sha256=schema_sha256,
                    query=self._queries.get(url),
                ),
            )
        next_index = min(index + 1, len(self._urls))
        return RecordPage(
            records=records,
            mode=SourceIngestionMode.FULL,
            strict_schema=False,
            checkpoint=_next_checkpoint(
                checkpoint,
                self.stream,
                index=index,
                next_index=next_index,
                url_digest=self._url_digest,
            ),
            exhausted=next_index >= len(self._urls),
        )

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        """Compare the fixed URL list with ``known_ids``; nothing live to call."""
        del session
        live = frozenset(self._urls)
        return ReconciliationReport(
            stream=self.stream,
            missing_from_source=tuple(sorted(known_ids - live)),
            unknown_to_sink=tuple(sorted(live - known_ids)),
        )
