"""The web-source contract a page connector implements (SCION-SOURCE-INGEST-R005.40).

A connector that fetches and extracts web pages serves two per-operation tools,
``web_fetch`` and ``web_extract``, through :func:`register_web_source_tools`.
Each takes one :class:`WebFetchRequest` and returns either a
:class:`WebPageResult` or a :class:`WebFetchRefusal` with a closed reason, so
every implementation has the same tool names, input and output schemas and
refusal reasons, whatever fetches the page. The SDK fetches and extracts
nothing itself: a connector supplies a :class:`WebSource`.

The contract states five obligations, checked by
:mod:`scion_sdk.testing.web_source_conformance`: obey ``robots.txt``
for the declared user agent; keep a per-domain rate limit (one request per
second by default); stop reading at ``max_bytes``; refuse an unlisted content
type; and make ``content_digest`` the SHA-256 of the returned text.
:class:`RobotsRules` and :class:`DomainRateLimiter` are the shared policy
helpers for the first two; the connector supplies how ``robots.txt`` is read.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from scion_sdk.ports._web_policy import (
    DEFAULT_MIN_INTERVAL_S,
    DomainRateLimiter,
    RobotsRules,
)
from scion_sdk.ports._web_refusal import (
    REFUSAL_REASONS,
    RefusalReason,
    WebFetchRefusal,
    WebSourceRefused,
)

__all__ = [
    "DEFAULT_ACCEPTED_TYPES",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MIN_INTERVAL_S",
    "REFUSAL_REASONS",
    "DomainRateLimiter",
    "RefusalReason",
    "RobotsRules",
    "WebFetchRefusal",
    "WebFetchRequest",
    "WebOutboundLink",
    "WebPageResult",
    "WebSource",
    "WebSourceRefused",
    "content_digest",
    "register_web_source_tools",
]

_logger = logging.getLogger(__name__)

#: The default byte cap of one page: 5 MiB.
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
#: Media types a page connector accepts unless the request narrows them.
DEFAULT_ACCEPTED_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/markdown",
)


class WebFetchRequest(BaseModel):
    """One page to fetch, with the caller's bounds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1, max_length=4096)
    max_bytes: int = Field(default=DEFAULT_MAX_BYTES, ge=1, le=64 * 1024 * 1024)
    accepted_types: tuple[str, ...] = DEFAULT_ACCEPTED_TYPES
    timeout_s: float = Field(default=30.0, gt=0, le=600)
    job_ref: str | None = Field(default=None, max_length=256)


class WebOutboundLink(BaseModel):
    """One outbound hyperlink of a page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    text: str = ""


class WebPageResult(BaseModel):
    """One fetched page; identical in shape whichever connector produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["page"] = "page"
    url: str
    canonical_url: str
    final_url: str
    status: int = Field(ge=100, le=599)
    content_type: str
    byte_count: int = Field(ge=0)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: str
    title: str = ""
    author: str = ""
    published_at: str = ""
    outbound_links: tuple[WebOutboundLink, ...] = ()
    text_markdown: str
    #: The connector that produced the page, recorded in provenance.
    backend: str = Field(min_length=1, max_length=128)


def content_digest(text: str) -> str:
    """The contract's ``content_digest``: SHA-256 of the returned text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@runtime_checkable
class WebSource(Protocol):
    """What a page connector supplies; raise :class:`WebSourceRefused` to refuse."""

    async def fetch(self, request: WebFetchRequest) -> WebPageResult: ...

    async def extract(self, request: WebFetchRequest) -> WebPageResult: ...


_TOOL_DESCRIPTIONS = {
    "web_fetch": (
        "Fetch one web page under the web-source contract: robots.txt, a "
        "per-domain rate limit, max_bytes and accepted_types. text_markdown "
        "holds the page body as text."
    ),
    "web_extract": (
        "Fetch one web page and extract its main content as markdown with "
        "title, author, published date, canonical URL and outbound links."
    ),
}


def register_web_source_tools(
    server: Any, source: WebSource | Callable[[], Any]
) -> tuple[str, ...]:
    """Register ``web_fetch`` and ``web_extract`` on a FastMCP ``server``.

    ``source`` is the connector's :class:`WebSource`, or a zero-argument
    callable returning one (resolved per call, so a connector can build it
    lazily from its settings). Both tools are read-only from the caller's
    view and idempotent; a :class:`WebSourceRefused` becomes a
    :class:`WebFetchRefusal` result, never a tool error.
    """
    from mcp.types import ToolAnnotations

    annotations = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )

    def _source() -> WebSource:
        return source if isinstance(source, WebSource) else source()

    async def _run(
        operation: str, request: WebFetchRequest
    ) -> WebPageResult | WebFetchRefusal:
        try:
            result: WebPageResult = await getattr(_source(), operation)(request)
        except WebSourceRefused as refused:
            return refused.refusal()
        if result.content_digest != content_digest(result.text_markdown):
            return WebFetchRefusal(
                reason="upstream_failed",
                detail="content_digest does not match the text",
            )
        return result

    async def web_fetch(request: WebFetchRequest) -> WebPageResult | WebFetchRefusal:
        return await _run("fetch", request)

    async def web_extract(request: WebFetchRequest) -> WebPageResult | WebFetchRefusal:
        return await _run("extract", request)

    for name, function in (("web_fetch", web_fetch), ("web_extract", web_extract)):
        server.tool(
            name=name,
            description=_TOOL_DESCRIPTIONS[name],
            annotations=annotations,
            tags={"web-source"},
        )(function)
    return ("web_fetch", "web_extract")
