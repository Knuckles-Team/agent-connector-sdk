"""Bounded, non-redirecting JSON state-change requests for source HTTP."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict, Unpack

import httpx

from ._http_client import (
    _ClientSpec,
    _prepare_client,
    _read_bounded,
    _read_bounded_async,
    _resolve_hop,
)
from ._http_headers import _headers_for_hop, _validated_headers
from ._http_proxy import _require_direct_peer
from ._http_resolve import normalize_allowed_hosts, require_safe_source_url
from ._http_types import (
    _REDIRECT_STATUS_CODES,
    DEFAULT_MAX_REQUEST_BYTES,
    DEFAULT_MAX_RESPONSE_BYTES,
    SourceEgressError,
    _reject_unknown_options,
    _require_byte_limit,
)
from ._http_urls import _logical_origin, _validate_timeout


class _WriteOptions(TypedDict, total=False):
    headers: dict[str, str] | None
    timeout: float
    max_bytes: int
    max_request_bytes: int
    allowed_private_hosts: Iterable[str] | None
    transport: Any
    tls_service: str


@dataclass
class _WriteCtx:
    method: str
    url: str
    body: bytes | None
    max_bytes: int
    transport: Any
    timeout: float
    tls_service: str
    headers: dict[str, str]
    private_hosts: frozenset[str]
    initial_origin: tuple[str, str, int]


def _encode_json_request_body(payload: Any, max_request_bytes: int) -> bytes:
    try:
        request_body = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        raise SourceEgressError("Source request was not valid JSON") from exc
    if len(request_body) > max_request_bytes:
        raise SourceEgressError("Source request exceeded the configured limit")
    return request_body


def _decode_json_response(raw: bytes, encoding: str | None) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode(encoding or "utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceEgressError("Source response was not valid JSON") from exc


def _open_write(
    url: str, payload: Any, options: Mapping[str, Any], *, method: str
) -> _WriteCtx:
    _reject_unknown_options(options, _WriteOptions)
    if method not in {"POST", "DELETE"}:
        raise ValueError("Only POST and DELETE JSON requests are supported")
    max_bytes = options.get("max_bytes", DEFAULT_MAX_RESPONSE_BYTES)
    max_request_bytes = options.get("max_request_bytes", DEFAULT_MAX_REQUEST_BYTES)
    _require_byte_limit("max_bytes", max_bytes)
    _require_byte_limit("max_request_bytes", max_request_bytes)
    body = (
        _encode_json_request_body(payload, max_request_bytes)
        if method == "POST"
        else None
    )
    timeout = _validate_timeout(options.get("timeout", 30.0))
    headers = _validated_headers(options.get("headers"))
    private_hosts = normalize_allowed_hosts(options.get("allowed_private_hosts"))
    require_safe_source_url(url, allowed_private_hosts=private_hosts, resolve_dns=False)
    return _WriteCtx(
        method=method,
        url=url,
        body=body,
        max_bytes=max_bytes,
        transport=options.get("transport"),
        timeout=timeout,
        tls_service=options.get("tls_service", "source-http"),
        headers=headers,
        private_hosts=private_hosts,
        initial_origin=_logical_origin(url),
    )


def _write_client(ctx: _WriteCtx, *, is_async: bool) -> _ClientSpec:
    return _prepare_client(
        ctx.transport, ctx.tls_service, ctx.timeout, is_async=is_async
    )


def _write_stream_args(ctx: _WriteCtx, spec: _ClientSpec) -> tuple[Any, dict[str, Any]]:
    """Resolve the single hop; return the resolution and ``client.stream`` kwargs."""
    resolution, request_url, extensions = _resolve_hop(
        ctx.transport, ctx.url, private_hosts=ctx.private_hosts, proxy=spec.proxy
    )
    hop_headers = _headers_for_hop(
        ctx.url, ctx.headers, initial_origin=ctx.initial_origin
    )
    if ctx.body is not None:
        hop_headers.setdefault("Content-Type", "application/json")
    return resolution, {
        "url": request_url,
        "content": ctx.body,
        "headers": hop_headers,
        "extensions": extensions,
    }


def _check_write_response(
    response: Any, resolution: Any, *, ctx: _WriteCtx, spec: _ClientSpec
) -> None:
    if ctx.transport is None:
        _require_direct_peer(response, resolution, spec.proxy)
    if response.status_code in _REDIRECT_STATUS_CODES:
        raise SourceEgressError("State-changing source redirect is forbidden")
    response.raise_for_status()


def _send_write(ctx: _WriteCtx, spec: _ClientSpec) -> Any:
    with spec.create_client(**spec.kwargs) as client:
        resolution, kwargs = _write_stream_args(ctx, spec)
        with client.stream(ctx.method, **kwargs) as response:
            _check_write_response(response, resolution, ctx=ctx, spec=spec)
            raw = _read_bounded(response, ctx.max_bytes)
            return _decode_json_response(raw, response.encoding)


async def _send_write_async(ctx: _WriteCtx, spec: _ClientSpec) -> Any:
    async with spec.create_client(**spec.kwargs) as client:
        resolution, kwargs = _write_stream_args(ctx, spec)
        async with client.stream(ctx.method, **kwargs) as response:
            _check_write_response(response, resolution, ctx=ctx, spec=spec)
            raw = await _read_bounded_async(response, ctx.max_bytes)
            return _decode_json_response(raw, response.encoding)


def _safe_write_json(
    method: str, url: str, payload: Any, **options: Unpack[_WriteOptions]
) -> Any:
    """Issue one bounded, non-redirecting JSON state-change request."""
    ctx = _open_write(url, payload, options, method=method)
    spec = _write_client(ctx, is_async=False)
    try:
        return _send_write(ctx, spec)
    except httpx.HTTPError:
        raise SourceEgressError("Source request failed") from None
    finally:
        spec.close()


async def safe_post_json_async(
    url: str, payload: Any, **options: Unpack[_WriteOptions]
) -> Any:
    """POST JSON to one validated endpoint and read one bounded JSON response.

    Redirects are rejected for state-changing requests. The destination is
    resolved immediately before I/O and uses the shared runtime TLS profile.
    """
    ctx = _open_write(url, payload, options, method="POST")
    spec = _write_client(ctx, is_async=True)
    try:
        return await _send_write_async(ctx, spec)
    except httpx.HTTPError:
        raise SourceEgressError("Source request failed") from None
    finally:
        spec.close()
