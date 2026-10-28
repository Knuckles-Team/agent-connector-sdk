"""The web-source contract and its conformance kit (SDK-SOURCE-INGEST-R005.40)."""

from __future__ import annotations

import asyncio
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from pydantic import ValidationError

from agent_connector_sdk.ports.web_source import (
    REFUSAL_REASONS,
    DomainRateLimiter,
    RobotsRules,
    WebFetchRefusal,
    WebFetchRequest,
    WebOutboundLink,
    WebPageResult,
    WebSourceRefused,
    content_digest,
    register_web_source_tools,
)
from agent_connector_sdk.testing.web_source_conformance import (
    check_web_source,
    fastmcp_caller,
    fixture_site,
    served_tool_schemas,
)

INTERVAL = 0.2


def _get(url: str, max_bytes: int) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return (
                response.status,
                response.headers.get("content-type", ""),
                response.read(max_bytes + 1),
            )
    except urllib.error.HTTPError as error:
        return error.code, "", b""


@dataclass
class FixtureSource:
    """A test page connector; ``broken`` drops every obligation."""

    backend: str = "fixture"
    broken: bool = False
    limiter: DomainRateLimiter = field(
        default_factory=lambda: DomainRateLimiter(min_interval_s=INTERVAL)
    )

    def __post_init__(self) -> None:
        async def load(url: str) -> tuple[int, str]:
            status, _ctype, body = await asyncio.to_thread(_get, url, 65536)
            return status, body.decode()

        self.robots = RobotsRules(load, user_agent="fixture")

    async def fetch(self, request: WebFetchRequest) -> WebPageResult:
        if not self.broken:
            await self.robots.check(request.url)
            await self.limiter.acquire(request.url)
        status, ctype, body = await asyncio.to_thread(
            _get, request.url, request.max_bytes
        )
        if not self.broken:
            if len(body) > request.max_bytes:
                raise WebSourceRefused("size_exceeded")
            if ctype.split(";")[0] not in request.accepted_types:
                raise WebSourceRefused("unsupported_type", ctype)
        text = body.decode("utf-8", "replace")
        return self._page(request, status, ctype, text, len(body))

    async def extract(self, request: WebFetchRequest) -> WebPageResult:
        page = await self.fetch(request)
        paragraphs = re.findall(r"<p>(.*?)</p>", page.text_markdown, re.S)
        text = "\n\n".join(re.sub(r"<[^>]+>", "", p) for p in paragraphs)
        return page.model_copy(
            update={
                "text_markdown": text,
                "content_digest": "0" * 64 if self.broken else content_digest(text),
                "title": "Disruption budgets",
            }
        )

    def _page(
        self, request: WebFetchRequest, status: int, ctype: str, text: str, size: int
    ) -> WebPageResult:
        return WebPageResult(
            url=request.url,
            canonical_url=request.url,
            final_url=request.url,
            status=status if 100 <= status <= 599 else 502,
            content_type=ctype or "application/octet-stream",
            byte_count=size,
            content_digest=content_digest(text),
            retrieved_at="2026-10-18T00:00:00+00:00",
            text_markdown=text,
            backend="other" if self.broken else self.backend,
        )


async def _report(source: FixtureSource) -> Any:
    server = FastMCP("fixture-web-source")
    register_web_source_tools(server, source)
    with fixture_site() as site:
        async with Client(server) as client:
            return await check_web_source(
                fastmcp_caller(client),
                site,
                backend="fixture",
                served_tools=await served_tool_schemas(client),
                min_interval_s=INTERVAL,
            )


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.40.1")
def test_models_round_trip() -> None:
    page = WebPageResult(
        url="https://example.org/a",
        canonical_url="https://example.org/a",
        final_url="https://example.org/a",
        status=200,
        content_type="text/html",
        byte_count=10,
        content_digest=content_digest("body"),
        retrieved_at="2026-10-18T00:00:00+00:00",
        title="A",
        author="B",
        published_at="2026-01-01",
        outbound_links=(WebOutboundLink(url="https://example.org/b", text="b"),),
        text_markdown="body",
        backend="webarchiver",
    )
    assert WebPageResult.model_validate(page.model_dump(mode="json")) == page
    request = WebFetchRequest(url="https://example.org/a")
    assert request.max_bytes == 5 * 1024 * 1024
    assert WebFetchRequest.model_validate(request.model_dump(mode="json")) == request
    refusal = WebFetchRefusal(reason="robots_disallowed", detail="d")
    assert WebFetchRefusal.model_validate(refusal.model_dump()) == refusal
    assert set(REFUSAL_REASONS) == {
        "robots_disallowed",
        "rate_limited",
        "size_exceeded",
        "unsupported_type",
        "egress_denied",
        "policy_refused",
        "extract_empty",
        "upstream_failed",
    }
    with pytest.raises(ValidationError):
        WebFetchRefusal(reason="nope")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        WebPageResult.model_validate({**page.model_dump(), "content_digest": "x"})
    with pytest.raises(ValueError):
        WebSourceRefused("nope")


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.40.2")
async def test_conformance_kit_flags_each_obligation() -> None:
    good = await _report(FixtureSource())
    assert good.ok, good.results
    bad = await _report(FixtureSource(broken=True))
    assert set(bad.broken) == {
        "robots",
        "max_bytes",
        "content_type",
        "content_digest",
        "rate_limit",
    }, bad.results


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.43")
async def test_domain_rate_limit_shares_host_across_schemes_and_ports() -> None:
    now = 0.0
    waits: list[float] = []

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        waits.append(delay)
        now += delay

    limiter = DomainRateLimiter(min_interval_s=1.0, clock=clock, sleep=sleep)
    await limiter.acquire("https://EXAMPLE.test/a")
    await limiter.acquire("http://example.test:8080/b")
    await limiter.acquire("https://example.test.:443/c")
    await limiter.acquire("https://other.test/a")
    assert waits == [1.0, 1.0]

    await limiter.acquire("https://[2001:db8::1]/a")
    await limiter.acquire("http://[2001:0db8::1]:8080/a")
    assert waits == [1.0, 1.0, 1.0]
    await limiter.acquire("https://bücher.example/a")
    await limiter.acquire("http://xn--bcher-kva.example/a")
    assert waits == [1.0, 1.0, 1.0, 1.0]
    await limiter.acquire("https://faß.example/a")
    await limiter.acquire("http://xn--fa-hia.example/a")
    assert waits == [1.0, 1.0, 1.0, 1.0, 1.0]
    with pytest.raises(WebSourceRefused, match="policy_refused"):
        await limiter.acquire("https://example.test:invalid/")


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.44")
async def test_robots_loads_canonical_ipv6_origin() -> None:
    loaded: list[str] = []

    async def load(url: str) -> tuple[int, str]:
        loaded.append(url)
        return 200, "User-agent: *\nDisallow: /private\n"

    rules = RobotsRules(load, user_agent="test")
    assert await rules.allowed("http://[2001:db8::1]:8080/public")
    assert not await rules.allowed("http://[2001:0db8::1]:8080/private")
    assert loaded == ["http://[2001:db8::1]:8080/robots.txt"]
    assert await rules.allowed("https://faß.example/public")
    assert not await rules.allowed("https://xn--fa-hia.example/private")
    assert loaded[-1] == "https://xn--fa-hia.example/robots.txt"
    assert len(loaded) == 2
    with pytest.raises(WebSourceRefused, match="policy_refused"):
        await rules.allowed("http://example.test:invalid/private")


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.45")
async def test_served_robots_refusal_omits_requested_url_and_query() -> None:
    async def load(_url: str) -> tuple[int, str]:
        return 200, "User-agent: *\nDisallow: /private\n"

    rules = RobotsRules(load, user_agent="test")

    class Source:
        async def fetch(self, request: WebFetchRequest) -> WebPageResult:
            await rules.check(request.url)
            raise AssertionError("denied URL must not be fetched")

        async def extract(self, request: WebFetchRequest) -> WebPageResult:
            return await self.fetch(request)

    server = FastMCP("robots-refusal")
    register_web_source_tools(server, Source())
    async with Client(server) as client:
        call = fastmcp_caller(client)
        refusal = await call(
            "web_fetch",
            {"request": {"url": "https://example.test/private?token=secret-value"}},
        )
    assert refusal["reason"] == "robots_disallowed"
    assert "secret-value" not in str(refusal)
    assert "/private" not in str(refusal)


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.40.1")
async def test_a_refusal_is_a_result_and_a_bad_digest_is_refused() -> None:
    server = FastMCP("fixture-web-source")

    @dataclass
    class Refusing:
        async def fetch(self, request: WebFetchRequest) -> WebPageResult:
            raise WebSourceRefused("egress_denied", "private address")

        async def extract(self, request: WebFetchRequest) -> WebPageResult:
            page = await FixtureSource().fetch(request)
            return page.model_copy(update={"content_digest": "0" * 64})

    register_web_source_tools(server, Refusing())
    with fixture_site() as site:
        async with Client(server) as client:
            call = fastmcp_caller(client)
            refused = await call(
                "web_fetch", {"request": {"url": f"{site.base_url}/article"}}
            )
            tampered = await call(
                "web_extract", {"request": {"url": f"{site.base_url}/article"}}
            )
    assert refused == {
        "kind": "refusal",
        "reason": "egress_denied",
        "detail": "private address",
    }
    assert tampered["kind"] == "refusal" and tampered["reason"] == "upstream_failed"


@pytest.mark.spec("SDK-SOURCE-INGEST-R005.40.1")
async def test_contract_defaults_protocol_and_kit_surface() -> None:
    from typing import get_args

    from agent_connector_sdk.ports.web_source import (
        DEFAULT_ACCEPTED_TYPES,
        DEFAULT_MAX_BYTES,
        DEFAULT_MIN_INTERVAL_S,
        RefusalReason,
        WebSource,
    )
    from agent_connector_sdk.testing.http_server import RoutedHttpServer, RoutedRequest
    from agent_connector_sdk.testing.web_source_conformance import (
        ARTICLE_SENTENCE,
        Caller,
        ConformanceReport,
        contract_tool_schemas,
    )

    assert DEFAULT_MAX_BYTES == 5 * 1024 * 1024
    assert DEFAULT_MIN_INTERVAL_S == 1.0
    assert "text/html" in DEFAULT_ACCEPTED_TYPES
    assert get_args(RefusalReason) == REFUSAL_REASONS
    assert isinstance(FixtureSource(), WebSource)
    schemas = await contract_tool_schemas()
    assert set(schemas) == {"web_fetch", "web_extract"}
    assert schemas["web_fetch"]["input"]["required"] == ["request"]
    report = ConformanceReport()
    report.record("robots", None)
    report.record("max_bytes", "not refused")
    assert report.broken == ("max_bytes",) and not report.ok
    with fixture_site() as site:
        assert isinstance(site, RoutedHttpServer)
        with urllib.request.urlopen(f"{site.base_url}/article", timeout=10) as response:
            assert ARTICLE_SENTENCE.encode() in response.read()
        (request,) = site.served("/article")
        assert isinstance(request, RoutedRequest) and request.path == "/article"

    async def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"tool": tool, **arguments}

    caller: Caller = call
    assert await caller("web_fetch", {"request": {}}) == {
        "tool": "web_fetch",
        "request": {},
    }
