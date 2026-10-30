"""Conformance kit for the web-source contract (SCION-SOURCE-INGEST-R005.40.2).

A page connector runs :func:`check_web_source` against its own served tools and
:func:`fixture_site`. Each obligation is checked by name, and the report names
every broken one:

* ``tool_surface``: ``web_fetch`` and ``web_extract`` with the contract's input
  and output schemas;
* ``robots``: a path ``robots.txt`` disallows is refused and never fetched;
* ``rate_limit``: two pages on one origin are fetched at least the minimum
  interval apart;
* ``max_bytes``: a body over ``max_bytes`` is refused with ``size_exceeded``;
* ``content_type``: an unlisted type is refused with ``unsupported_type``;
* ``content_digest``: a page's digest is the SHA-256 of its returned text, and
  the page names the connector as ``backend``.

``call(tool, arguments)`` invokes one served tool and returns its structured
result; :func:`fastmcp_caller` builds one for an in-process FastMCP client.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from scion_sdk.ports.web_source import (
    DEFAULT_MIN_INTERVAL_S,
    WebFetchRefusal,
    WebPageResult,
    content_digest,
)
from scion_sdk.testing.http_server import RoutedHttpServer, ScriptedResponse

__all__ = [
    "ARTICLE_SENTENCE",
    "Caller",
    "ConformanceReport",
    "check_web_source",
    "contract_tool_schemas",
    "fastmcp_caller",
    "fixture_site",
    "served_tool_schemas",
]

#: A sentence the fixture article's main content contains.
ARTICLE_SENTENCE = (
    "A pod disruption budget limits how many replicas a voluntary disruption "
    "may take down at once."
)
_ARTICLE = (
    "<!doctype html><html><head><title>Disruption budgets</title>"
    '<meta name="author" content="Fixture Author"></head><body>'
    "<nav>Home · Docs</nav><article><h1>Disruption budgets</h1>"
    + "".join(
        f"<p>{ARTICLE_SENTENCE} Paragraph {n} explains drains and evictions.</p>"
        for n in range(8)
    )
    + '<p>See <a href="https://example.org/reference">the reference</a>.</p>'
    "</article><footer>Fixture footer</footer></body></html>"
).encode()

Caller = Callable[[str, dict[str, Any]], Awaitable[Mapping[str, Any]]]


def fixture_site() -> RoutedHttpServer:
    """The kit's loopback site: an article, a second page, a disallowed path,
    an image and an oversized page. Use it as a context manager."""
    html = {"Content-Type": "text/html; charset=utf-8"}
    return RoutedHttpServer(
        {
            "/robots.txt": ScriptedResponse(
                body=b"User-agent: *\nDisallow: /private/\n",
                headers={"Content-Type": "text/plain"},
            ),
            "/article": ScriptedResponse(body=_ARTICLE, headers=html),
            "/article-two": ScriptedResponse(body=_ARTICLE, headers=html),
            "/private/page": ScriptedResponse(body=_ARTICLE, headers=html),
            "/image.png": ScriptedResponse(
                body=b"\x89PNG\r\n\x1a\n" + b"0" * 64,
                headers={"Content-Type": "image/png"},
            ),
            "/huge": ScriptedResponse(
                body=b"<html><body><p>" + b"x" * 8192 + b"</p></body></html>",
                headers=html,
            ),
        }
    )


@dataclass
class ConformanceReport:
    """Each obligation's outcome; ``broken`` names the failed ones."""

    results: dict[str, str] = field(default_factory=dict)

    def record(self, obligation: str, problem: str | None) -> None:
        self.results[obligation] = problem or "ok"

    @property
    def broken(self) -> tuple[str, ...]:
        return tuple(name for name, value in self.results.items() if value != "ok")

    @property
    def ok(self) -> bool:
        return not self.broken


async def contract_tool_schemas() -> dict[str, dict[str, Any]]:
    """The contract's ``{tool: {"input": schema, "output": schema}}``."""
    from fastmcp import Client, FastMCP

    from scion_sdk.ports.web_source import register_web_source_tools

    reference = FastMCP("web-source-contract")

    class _Unused:
        async def fetch(self, request: Any) -> Any:  # pragma: no cover - never called
            raise AssertionError("reference only")

        extract = fetch

    register_web_source_tools(reference, _Unused())
    async with Client(reference) as client:
        return await served_tool_schemas(client)


async def served_tool_schemas(client: Any) -> dict[str, dict[str, Any]]:
    """A connected client's ``web_fetch``/``web_extract`` input and output schemas."""
    return {
        tool.name: {"input": tool.inputSchema, "output": tool.outputSchema}
        for tool in await client.list_tools()
        if tool.name in {"web_fetch", "web_extract"}
    }


def fastmcp_caller(client: Any) -> Caller:
    """A :data:`Caller` over a connected ``fastmcp.Client``."""

    async def call(tool: str, arguments: dict[str, Any]) -> Mapping[str, Any]:
        result = await client.call_tool(tool, arguments, raise_on_error=False)
        body = result.structured_content
        if body is None and result.content:
            body = json.loads(result.content[0].text)
        if isinstance(body, Mapping) and set(body) == {"result"}:
            body = body["result"]
        return body or {}

    return call


def _parsed(body: Mapping[str, Any]) -> WebPageResult | WebFetchRefusal | str:
    try:
        if body.get("kind") == "refusal":
            return WebFetchRefusal.model_validate(body)
        return WebPageResult.model_validate(body)
    except Exception as exc:
        return f"result does not match the contract: {exc}"[:300]


def _refused(outcome: Any, reason: str) -> str | None:
    if isinstance(outcome, str):
        return outcome
    if not isinstance(outcome, WebFetchRefusal):
        return f"expected a {reason} refusal, got a page"
    return (
        None
        if outcome.reason == reason
        else f"refused with {outcome.reason}, not {reason}"
    )


async def check_web_source(
    call: Caller,
    site: RoutedHttpServer,
    *,
    backend: str,
    served_tools: Mapping[str, Mapping[str, Any]],
    min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
    fetched_paths: Callable[[], Iterable[str]] | None = None,
) -> ConformanceReport:
    """Check every obligation of the connector behind ``call``.

    ``served_tools`` is the connector's own ``{tool: {"input", "output"}}``
    listing. ``fetched_paths`` names the paths the connector's fetcher
    requested from ``site``; it defaults to the site's own request log, and a
    connector whose fetcher is not a direct client of the site (an archiving
    service) supplies its own.
    """
    report = ConformanceReport()
    expected = await contract_tool_schemas()
    mismatched = [
        name for name, schema in expected.items() if served_tools.get(name) != schema
    ]
    report.record(
        "tool_surface",
        f"schemas differ from the contract for {mismatched}" if mismatched else None,
    )
    paths = fetched_paths or (lambda: (request.path for request in site.requests))
    base = site.base_url

    private = _parsed(
        await call("web_extract", {"request": {"url": f"{base}/private/page"}})
    )
    problem = _refused(private, "robots_disallowed")
    if problem is None and "/private/page" in set(paths()):
        problem = "the disallowed page was fetched"
    report.record("robots", problem)

    huge = _parsed(
        await call("web_fetch", {"request": {"url": f"{base}/huge", "max_bytes": 1024}})
    )
    report.record("max_bytes", _refused(huge, "size_exceeded"))

    image = _parsed(await call("web_fetch", {"request": {"url": f"{base}/image.png"}}))
    report.record("content_type", _refused(image, "unsupported_type"))

    page = _parsed(await call("web_extract", {"request": {"url": f"{base}/article"}}))
    if isinstance(page, WebPageResult):
        problems = []
        if page.content_digest != content_digest(page.text_markdown):
            problems.append("content_digest is not the SHA-256 of text_markdown")
        if page.backend != backend:
            problems.append(f"backend is {page.backend!r}, not {backend!r}")
        if ARTICLE_SENTENCE.split(" may ")[0] not in page.text_markdown:
            problems.append("the main content is missing")
        report.record("content_digest", "; ".join(problems) or None)
    else:
        report.record(
            "content_digest",
            page if isinstance(page, str) else f"refused: {page.reason}",
        )

    await call("web_extract", {"request": {"url": f"{base}/article-two"}})
    times = sorted(
        request.at
        for request in site.requests
        if request.path in {"/article", "/article-two"}
    )
    spaced = len(times) >= 2 and all(
        later - earlier >= min_interval_s * 0.9
        for earlier, later in itertools.pairwise(times)
    )
    report.record(
        "rate_limit",
        None if spaced else f"pages were not spaced {min_interval_s}s apart",
    )
    return report
