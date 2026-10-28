"""The requests-floor web-fetch backend: one URL fetched as markdown.

Ported from ``agent_utilities.knowledge_graph.ingestion.web_fetch``
(SDK-SOURCE-INGEST-R005) onto this SDK's own governed HTTP client
(:mod:`agent_connector_sdk.http.client`) instead of agent-utilities' bespoke
HTTP policy, since agent-utilities is not a dependency of this package.

This module ports only the zero-dependency ``requests`` floor: the HTTP GET,
Open Graph/Twitter Card metadata extraction, and markdown normalization. The
ArchiveBox and crawl4ai backends stay in agent-utilities for now (they call
back into agent-utilities-owned infrastructure: the MCP tool fleet and the
skill-graph crawler subprocess); both remain as open lines in
``specs/SDK-SOURCE-INGEST/tasks.md``.

:class:`WebFetchSourceAdapter` wires ``fetch_page`` behind ``ports.SourceAdapter``:
its stream is a fixed, ordered list of URLs declared at construction (not a
live MCP tool contract), one URL fetched per extracted page, so the generated
SourceIngest client can reach it through the same ``discover``/``extract``/
``reconcile`` surface every other adapter uses.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence

import httpx
from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceRecord,
    SourceRecordProvenance,
)
from pydantic import BaseModel, ConfigDict, Field

from agent_connector_sdk.adapters.web_fetch_checkpoint import (
    _next_checkpoint,
    _page_index,
)
from agent_connector_sdk.adapters.web_fetch_helpers import (
    _markdown_from_html,
    extract_og_metadata,
)
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

__all__ = [
    "FetchedPage",
    "WebFetchSourceAdapter",
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

_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


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
        raw = await _read_web_text(options)
    except (httpx.HTTPError, ResponseTooLargeError):
        return None
    if raw is None:
        return None
    text = _markdown_from_html(raw)
    if not text.strip():
        return None
    og = extract_og_metadata(raw)
    title_match = _TITLE_TAG_RE.search(raw)
    title = og["title"] or (title_match.group(1).strip() if title_match else "")
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


def _record_from_page(
    page: FetchedPage, *, stream: str, connector: str, mapping_reference: str
) -> SourceRecord:
    return SourceRecord(
        stream=stream,
        record_id=page.url,
        payload=page.model_dump(mode="json"),
        mapping_reference=mapping_reference,
        provenance=SourceRecordProvenance(
            adapter_kind=WebFetchSourceAdapter.kind,
            connector=connector,
            server=WebFetchSourceAdapter.kind,
            source_uri=page.url,
            tool=WebFetchSourceAdapter.kind,
            tool_schema_sha256=_SCHEMA_SHA256,
        ),
    )


class WebFetchSourceAdapter:
    """Fetch a fixed, ordered list of URLs; one URL extracted per page.

    Unlike :class:`~agent_connector_sdk.adapters.mcp_tool.McpToolSourceAdapter`,
    this adapter's stream is not a live MCP tool contract: its URL list is
    declared at construction, so ``discover`` verifies nothing live and
    ``extract``/``reconcile`` never call ``session``. The parameter is kept
    to conform to :class:`~agent_connector_sdk.ports.source_adapter.SourceAdapter`.
    Private-host and plaintext exceptions must be provided by the caller.
    """

    kind = "web_fetch"

    def __init__(
        self,
        urls: Sequence[str],
        *,
        connector: str,
        mapping_reference: str,
        allowed_private_hosts: Sequence[str] = (),
        allow_plaintext: bool = False,
    ) -> None:
        self._urls = tuple(urls)
        encoded_urls = json.dumps(
            self._urls, ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        self._url_digest = hashlib.sha256(encoded_urls).hexdigest()
        self._connector = connector
        self._mapping_reference = mapping_reference
        self._allowed_private_hosts = tuple(allowed_private_hosts)
        self._allow_plaintext = allow_plaintext

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
        """Declare the fixed stream; there is no live tool contract to verify."""
        del session
        return StreamDescriptor(
            stream=self.stream, tool=self.kind, schema_sha256=_SCHEMA_SHA256
        )

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        """Fetch the next URL in this adapter's fixed list, if any remain."""
        del session
        index = _page_index(
            checkpoint, self.stream, count=len(self._urls), url_digest=self._url_digest
        )
        records: tuple[SourceRecord, ...] = ()
        if index < len(self._urls):
            page = await fetch_page(
                self._urls[index],
                allowed_private_hosts=self._allowed_private_hosts,
                allow_plaintext=self._allow_plaintext,
            )
            if page is None:
                raise SourceContractError("web fetch failed or returned empty content")
            records = (
                _record_from_page(
                    page,
                    stream=self.stream,
                    connector=self._connector,
                    mapping_reference=self._mapping_reference,
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
