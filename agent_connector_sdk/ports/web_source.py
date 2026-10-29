"""The web-source contract a page connector implements (SCION-SOURCE-INGEST-R005.40).

A connector that fetches and extracts web pages serves two per-operation tools,
``web_fetch`` and ``web_extract``, through :func:`register_web_source_tools`.
Each takes one :class:`WebFetchRequest` and returns either a
:class:`WebPageResult` or a :class:`WebFetchRefusal` with a closed reason, so
every implementation has the same tool names, input and output schemas and
refusal reasons, whatever fetches the page. The SDK fetches and extracts
nothing itself: a connector supplies a :class:`WebSource`.

The contract states five obligations, checked by
:mod:`agent_connector_sdk.testing.web_source_conformance`: obey ``robots.txt``
for the declared user agent; keep a per-domain rate limit (one request per
second by default); stop reading at ``max_bytes``; refuse an unlisted content
type; and make ``content_digest`` the SHA-256 of the returned text.
:class:`RobotsRules` and :class:`DomainRateLimiter` are the shared policy
helpers for the first two; the connector supplies how ``robots.txt`` is read.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import time
import urllib.robotparser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

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
#: The default per-domain spacing: one request per second.
DEFAULT_MIN_INTERVAL_S = 1.0
#: Media types a page connector accepts unless the request narrows them.
DEFAULT_ACCEPTED_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/markdown",
)

RefusalReason = Literal[
    "robots_disallowed",
    "rate_limited",
    "size_exceeded",
    "unsupported_type",
    "egress_denied",
    "policy_refused",
    "extract_empty",
    "upstream_failed",
]
#: The closed refusal reasons, in contract order.
REFUSAL_REASONS: tuple[str, ...] = RefusalReason.__args__  # type: ignore[attr-defined]


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


class WebFetchRefusal(BaseModel):
    """A connector's refusal of one page, with a closed reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["refusal"] = "refusal"
    reason: RefusalReason
    detail: str = Field(default="", max_length=2000)


class WebSourceRefused(Exception):
    """Raised by a :class:`WebSource`; the tools return it as a refusal."""

    def __init__(self, reason: str, detail: str = "") -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError(f"unknown web-source refusal reason {reason!r}")
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)

    def refusal(self) -> WebFetchRefusal:
        return WebFetchRefusal(reason=self.reason, detail=self.detail[:2000])  # type: ignore[arg-type]


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


# --------------------------------------------------------------------- policy


def _origin(url: str) -> str:
    try:
        parts = httpx.URL(url)
        host = parts.raw_host.decode("ascii").rstrip(".")
        if parts.scheme not in {"http", "https"} or not host:
            raise ValueError("absolute URL required")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            authority = host.lower()
        else:
            authority = f"[{address}]" if address.version == 6 else str(address)
        port = f":{parts.port}" if parts.port is not None else ""
        return f"{parts.scheme}://{authority}{port}"
    except (httpx.InvalidURL, UnicodeError, ValueError) as exc:
        raise WebSourceRefused("policy_refused", "invalid web URL") from exc


def _rate_limit_domain(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port
        if parts.scheme not in {"http", "https"} or not host:
            raise ValueError("absolute URL required")
        host = httpx.URL(url).raw_host.decode("ascii").rstrip(".")
        if not host or any(char.isspace() for char in host):
            raise ValueError("invalid host")
        try:
            return str(ipaddress.ip_address(host))
        except ValueError:
            return host.lower()
    except (httpx.InvalidURL, UnicodeError, ValueError) as exc:
        raise WebSourceRefused("policy_refused", "invalid web URL") from exc


@dataclass
class DomainRateLimiter:
    """Space requests to one host at least ``min_interval_s`` apart."""

    min_interval_s: float = DEFAULT_MIN_INTERVAL_S
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    _next: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    async def acquire(self, url: str) -> None:
        domain = _rate_limit_domain(url)
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            now = self.clock()
            wait = self._next.get(domain, now) - now
            if wait > 0:
                await self.sleep(wait)
                now = self.clock()
            self._next[domain] = now + self.min_interval_s


RobotsLoader = Callable[[str], Awaitable[tuple[int, str]]]


@dataclass
class RobotsRules:
    """``robots.txt`` per origin, cached for ``ttl_s`` (one hour by default).

    ``loader`` reads one ``robots.txt`` URL and returns ``(status, body)``; the
    connector supplies it, so the SDK makes no request itself. A 4xx file allows
    everything (RFC 9309 section 2.3.1.3); a 5xx or failed read disallows
    everything until the entry expires.
    """

    loader: RobotsLoader
    user_agent: str
    ttl_s: float = 3600.0
    clock: Callable[[], float] = time.monotonic
    _rules: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = field(
        default_factory=dict
    )
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    async def check(self, url: str) -> None:
        """Raise ``robots_disallowed`` unless ``url`` may be fetched."""
        if not await self.allowed(url):
            raise WebSourceRefused(
                "robots_disallowed", "robots policy disallows the page"
            )

    async def allowed(self, url: str) -> bool:
        origin = _origin(url)
        cached = self._rules.get(origin)
        if cached is None or cached[0] < self.clock():
            lock = self._locks.setdefault(origin, asyncio.Lock())
            async with lock:
                cached = self._rules.get(origin)
                if cached is None or cached[0] < self.clock():
                    parser = await self._load(origin)
                    cached = (self.clock() + self.ttl_s, parser)
                    self._rules[origin] = cached
        return cached[1].can_fetch(self.user_agent, url)

    async def _load(self, origin: str) -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser()
        try:
            status, body = await self.loader(f"{origin}/robots.txt")
        except WebSourceRefused as refused:
            if refused.reason in {"egress_denied", "policy_refused"}:
                raise
            status, body = 503, ""
        except Exception as exc:
            # RFC 9309: an unreachable robots.txt disallows the whole origin.
            _logger.info(
                "robots.txt for %s is unreadable: %s", origin, type(exc).__name__
            )
            status, body = 503, ""
        if status >= 500:
            # RobotFileParser's documented switches are not in its type stubs.
            vars(parser).update(disallow_all=True)
        elif status >= 400:
            vars(parser).update(allow_all=True)
        else:
            parser.parse(body.splitlines())
        return parser
