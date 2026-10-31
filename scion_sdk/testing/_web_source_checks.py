"""Per-obligation checks behind :func:`web_source_conformance.check_web_source`."""

from __future__ import annotations

import itertools
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from scion_sdk.ports.web_source import (
    WebFetchRefusal,
    WebPageResult,
    content_digest,
)
from scion_sdk.testing.http_server import RoutedHttpServer

Caller = Callable[[str, dict[str, Any]], Awaitable[Mapping[str, Any]]]


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


async def _tool_surface_problem(
    expected: Mapping[str, Any], served_tools: Mapping[str, Mapping[str, Any]]
) -> str | None:
    mismatched = [
        name for name, schema in expected.items() if served_tools.get(name) != schema
    ]
    return f"schemas differ from the contract for {mismatched}" if mismatched else None


async def _robots_problem(
    call: Caller, base: str, fetched_paths: Callable[[], Any]
) -> str | None:
    private = _parsed(
        await call("web_extract", {"request": {"url": f"{base}/private/page"}})
    )
    problem = _refused(private, "robots_disallowed")
    if problem is None and "/private/page" in set(fetched_paths()):
        problem = "the disallowed page was fetched"
    return problem


async def _max_bytes_problem(call: Caller, base: str) -> str | None:
    huge = _parsed(
        await call("web_fetch", {"request": {"url": f"{base}/huge", "max_bytes": 1024}})
    )
    return _refused(huge, "size_exceeded")


async def _content_type_problem(call: Caller, base: str) -> str | None:
    image = _parsed(await call("web_fetch", {"request": {"url": f"{base}/image.png"}}))
    return _refused(image, "unsupported_type")


async def _content_digest_problem(
    call: Caller, base: str, *, backend: str, marker: str
) -> str | None:
    page = _parsed(await call("web_extract", {"request": {"url": f"{base}/article"}}))
    if not isinstance(page, WebPageResult):
        return page if isinstance(page, str) else f"refused: {page.reason}"
    problems = []
    if page.content_digest != content_digest(page.text_markdown):
        problems.append("content_digest is not the SHA-256 of text_markdown")
    if page.backend != backend:
        problems.append(f"backend is {page.backend!r}, not {backend!r}")
    if marker not in page.text_markdown:
        problems.append("the main content is missing")
    return "; ".join(problems) or None


async def _rate_limit_problem(
    call: Caller, site: RoutedHttpServer, base: str, *, min_interval_s: float
) -> str | None:
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
    return None if spaced else f"pages were not spaced {min_interval_s}s apart"
