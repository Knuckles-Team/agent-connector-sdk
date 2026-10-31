"""Per-hop planning and redirect policy for the source HTTP fetch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from ._http_client import _ClientSpec, _resolve_hop
from ._http_headers import _headers_for_hop
from ._http_proxy import _require_direct_peer
from ._http_resolve import require_safe_source_url
from ._http_types import _REDIRECT_STATUS_CODES, ResolvedSourceURL, SourceEgressError
from ._http_urls import _validate_url_shape


@dataclass
class _FetchCtx:
    """Policy-checked state shared by every hop of one fetch."""

    client: _ClientSpec
    transport: Any
    max_bytes: int
    max_redirects: int
    headers: dict[str, str]
    private_hosts: frozenset[str]
    permitted_redirect_hosts: set[str]
    initial_origin: tuple[str, str, int]
    first_params: dict[str, Any]


@dataclass
class _HopPlan:
    resolution: ResolvedSourceURL
    request_url: str
    logical_url: str
    stream_kwargs: dict[str, Any]


def _plan_hop(ctx: _FetchCtx, current: str, params: dict[str, Any]) -> _HopPlan:
    resolution, request_url, extensions = _resolve_hop(
        ctx.transport,
        current,
        private_hosts=ctx.private_hosts,
        proxy=ctx.client.proxy,
    )
    if resolution.host not in ctx.permitted_redirect_hosts:
        raise SourceEgressError("Cross-host source redirect is not permitted")
    logical_url = str(httpx.URL(current, params=params))
    _validate_url_shape(logical_url)
    hop_headers = _headers_for_hop(
        current, ctx.headers, initial_origin=ctx.initial_origin
    )
    return _HopPlan(
        resolution=resolution,
        request_url=request_url,
        logical_url=logical_url,
        stream_kwargs={
            "params": params,
            "headers": hop_headers,
            "extensions": extensions,
        },
    )


def _next_redirect_url(
    ctx: _FetchCtx, response: Any, plan: _HopPlan, *, hop: int
) -> str:
    if hop >= ctx.max_redirects:
        raise SourceEgressError("Source redirect limit exceeded")
    location = response.headers.get("location")
    if not location:
        raise SourceEgressError("Source redirect omitted its destination")
    destination = urljoin(plan.logical_url, location)
    next_url = _validate_url_shape(destination)
    next_host = require_safe_source_url(
        destination, allowed_private_hosts=ctx.private_hosts, resolve_dns=False
    )
    if next_host not in ctx.permitted_redirect_hosts:
        raise SourceEgressError("Cross-host source redirect is not permitted")
    if plan.resolution.scheme == "https" and next_url.scheme == "http":
        raise SourceEgressError("HTTPS source redirect downgrade is forbidden")
    return str(destination)


def _redirect_target(
    ctx: _FetchCtx, response: Any, plan: _HopPlan, *, hop: int
) -> str | None:
    """Return the next hop URL for a redirect, or ``None`` for a final response."""
    if ctx.transport is None:
        _require_direct_peer(response, plan.resolution, ctx.client.proxy)
    if response.status_code in _REDIRECT_STATUS_CODES:
        return _next_redirect_url(ctx, response, plan, hop=hop)
    response.raise_for_status()
    return None
