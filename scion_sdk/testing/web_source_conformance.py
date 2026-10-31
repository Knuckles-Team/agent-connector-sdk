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

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from scion_sdk.ports.web_source import (
    DEFAULT_MIN_INTERVAL_S,
)
from scion_sdk.testing._web_source_checks import (
    Caller,
    _content_digest_problem,
    _content_type_problem,
    _max_bytes_problem,
    _rate_limit_problem,
    _robots_problem,
    _tool_surface_problem,
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
    report.record("tool_surface", await _tool_surface_problem(expected, served_tools))
    paths = fetched_paths or (lambda: (request.path for request in site.requests))
    base = site.base_url
    report.record("robots", await _robots_problem(call, base, paths))
    report.record("max_bytes", await _max_bytes_problem(call, base))
    report.record("content_type", await _content_type_problem(call, base))
    marker = ARTICLE_SENTENCE.split(" may ")[0]
    report.record(
        "content_digest",
        await _content_digest_problem(call, base, backend=backend, marker=marker),
    )
    report.record(
        "rate_limit",
        await _rate_limit_problem(call, site, base, min_interval_s=min_interval_s),
    )
    return report
