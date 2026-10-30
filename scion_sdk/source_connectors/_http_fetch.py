"""Redirect-checked, DNS-pinned bounded GET for the source HTTP boundary."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict, Unpack

import httpx

from ._http_client import (
    _prepare_client,
    _read_bounded,
    _read_bounded_async,
)
from ._http_headers import _validated_headers, _validated_params
from ._http_hops import _FetchCtx, _plan_hop, _redirect_target
from ._http_resolve import normalize_allowed_hosts, require_safe_source_url
from ._http_types import (
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_MAX_RESPONSE_BYTES,
    HARD_MAX_REDIRECTS,
    SourceEgressError,
    _reject_unknown_options,
    _require_byte_limit,
)
from ._http_urls import _logical_origin, _validate_timeout


class _FetchOptions(TypedDict, total=False):
    params: dict[str, Any] | None
    headers: dict[str, str] | None
    timeout: float
    max_bytes: int
    max_redirects: int
    allowed_private_hosts: Iterable[str] | None
    allowed_redirect_hosts: Iterable[str] | None
    transport: Any
    tls_service: str


def _validated_fetch_limits(options: Mapping[str, Any]) -> tuple[int, int]:
    _reject_unknown_options(options, _FetchOptions)
    max_redirects = options.get("max_redirects", DEFAULT_MAX_REDIRECTS)
    max_bytes = options.get("max_bytes", DEFAULT_MAX_RESPONSE_BYTES)
    if not 0 <= max_redirects <= HARD_MAX_REDIRECTS:
        raise ValueError(f"max_redirects must be between 0 and {HARD_MAX_REDIRECTS}")
    _require_byte_limit("max_bytes", max_bytes)
    return max_redirects, max_bytes


def _open_fetch(url: str, options: Mapping[str, Any], *, is_async: bool) -> _FetchCtx:
    max_redirects, max_bytes = _validated_fetch_limits(options)
    timeout = _validate_timeout(options.get("timeout", 30.0))
    headers = _validated_headers(options.get("headers"))
    private_hosts = normalize_allowed_hosts(options.get("allowed_private_hosts"))
    redirect_hosts = normalize_allowed_hosts(options.get("allowed_redirect_hosts"))
    initial_host = require_safe_source_url(
        url, allowed_private_hosts=private_hosts, resolve_dns=False
    )
    initial_origin = _logical_origin(url)
    first_params = _validated_params(options.get("params"))
    transport = options.get("transport")
    client = _prepare_client(
        transport, options.get("tls_service", "source-http"), timeout, is_async=is_async
    )
    return _FetchCtx(
        client=client,
        transport=transport,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        headers=headers,
        private_hosts=private_hosts,
        permitted_redirect_hosts={initial_host, *redirect_hosts},
        initial_origin=initial_origin,
        first_params=first_params,
    )


@dataclass
class _HopState:
    current: str
    params: dict[str, Any]


_NO_RESPONSE = "Source fetch did not produce a response"


def _fetch_hop(
    ctx: _FetchCtx, client: Any, state: _HopState, *, hop: int
) -> tuple[bytes, str | None] | None:
    plan = _plan_hop(ctx, state.current, state.params)
    with client.stream("GET", plan.request_url, **plan.stream_kwargs) as r:
        target = _redirect_target(ctx, r, plan, hop=hop)
        if target is None:
            return _read_bounded(r, ctx.max_bytes), r.encoding
    state.current, state.params = target, {}
    return None


async def _fetch_hop_async(
    ctx: _FetchCtx, client: Any, state: _HopState, *, hop: int
) -> tuple[bytes, str | None] | None:
    plan = _plan_hop(ctx, state.current, state.params)
    async with client.stream("GET", plan.request_url, **plan.stream_kwargs) as r:
        target = _redirect_target(ctx, r, plan, hop=hop)
        if target is None:
            return await _read_bounded_async(r, ctx.max_bytes), r.encoding
    state.current, state.params = target, {}
    return None


def _fetch_all(ctx: _FetchCtx, url: str) -> tuple[bytes, str | None]:
    state = _HopState(url, ctx.first_params)
    with ctx.client.create_client(**ctx.client.kwargs) as client:
        for hop in range(ctx.max_redirects + 1):
            result = _fetch_hop(ctx, client, state, hop=hop)
            if result is not None:
                return result
    raise SourceEgressError(_NO_RESPONSE)


async def _fetch_all_async(ctx: _FetchCtx, url: str) -> tuple[bytes, str | None]:
    state = _HopState(url, ctx.first_params)
    async with ctx.client.create_client(**ctx.client.kwargs) as client:
        for hop in range(ctx.max_redirects + 1):
            result = await _fetch_hop_async(ctx, client, state, hop=hop)
            if result is not None:
                return result
    raise SourceEgressError(_NO_RESPONSE)


def safe_get_bytes(
    url: str, **options: Unpack[_FetchOptions]
) -> tuple[bytes, str | None]:
    """Fetch a bounded body with a DNS-pinned, hop-by-hop egress policy."""
    ctx = _open_fetch(url, options, is_async=False)
    try:
        return _fetch_all(ctx, url)
    except httpx.HTTPError:
        raise SourceEgressError("Source fetch failed") from None
    finally:
        ctx.client.close()


async def safe_get_bytes_async(
    url: str, **options: Unpack[_FetchOptions]
) -> tuple[bytes, str | None]:
    """Async equivalent of :func:`safe_get_bytes` with identical policy."""
    ctx = _open_fetch(url, options, is_async=True)
    try:
        return await _fetch_all_async(ctx, url)
    except httpx.HTTPError:
        raise SourceEgressError("Source fetch failed") from None
    finally:
        ctx.client.close()
