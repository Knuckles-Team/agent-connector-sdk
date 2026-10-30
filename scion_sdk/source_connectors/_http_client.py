"""Client construction, hop resolution and bounded reads for source HTTP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from ._http_headers import _request_extensions
from ._http_proxy import (
    _pin_configured_proxy,
    _profile_httpx_kwargs,
    _require_proxy_target_compatibility,
)
from ._http_resolve import resolve_safe_source_url
from ._http_types import (
    ResolvedSourceURL,
    SourceEgressError,
    _PinnedProxy,
    _require_byte_limit,
)
from ._http_urls import _normalize_hostname, _pinned_url, _validate_url_shape

_LIMIT_MESSAGE = "Source response exceeded the configured limit"


def _check_declared_length(response: Any, max_bytes: int) -> None:
    _require_byte_limit("max_bytes", max_bytes)
    length = response.headers.get("content-length")
    if not length:
        return
    try:
        declared_length = int(length)
    except ValueError:
        return
    if declared_length > max_bytes:
        raise SourceEgressError(_LIMIT_MESSAGE)


def _append_chunk(body: bytearray, chunk: bytes, max_bytes: int) -> None:
    if len(chunk) > max_bytes - len(body):
        raise SourceEgressError(_LIMIT_MESSAGE)
    body.extend(chunk)


def _read_bounded(response: Any, max_bytes: int) -> bytes:
    _check_declared_length(response, max_bytes)
    body = bytearray()
    for chunk in response.iter_bytes():
        _append_chunk(body, chunk, max_bytes)
    return bytes(body)


async def _read_bounded_async(response: Any, max_bytes: int) -> bytes:
    _check_declared_length(response, max_bytes)
    body = bytearray()
    async for chunk in response.aiter_bytes():
        _append_chunk(body, chunk, max_bytes)
    return bytes(body)


@dataclass
class _ClientSpec:
    """httpx client kwargs plus the TLS profile and proxy that must be released."""

    kwargs: dict[str, Any]
    create_client: Any
    tls: Any = None
    proxy: _PinnedProxy | None = field(default=None)

    def close(self) -> None:
        if self.tls is not None:
            self.tls.cleanup()


def _attach_tls_profile(spec: _ClientSpec, tls_service: str) -> None:
    from scion_sdk.tls.resolve import resolve_tls_profile

    spec.tls = resolve_tls_profile(tls_service)
    spec.proxy = _pin_configured_proxy(spec.tls.proxy_url)
    spec.kwargs.update(_profile_httpx_kwargs(spec.tls, spec.proxy))


def _prepare_client(
    transport: Any,
    tls_service: str,
    timeout: float,
    *,
    is_async: bool,
) -> _ClientSpec:
    """Build the client spec; a failed profile resolution releases its TLS profile."""
    spec = _ClientSpec(
        kwargs={"timeout": timeout, "follow_redirects": False},
        create_client=httpx.AsyncClient if is_async else httpx.Client,
    )
    if transport is not None:
        spec.kwargs["transport"] = transport
        return spec
    try:
        _attach_tls_profile(spec, tls_service)
    except BaseException:
        spec.close()
        raise
    return spec


def _resolve_pinned_hop(
    current: str, private_hosts: frozenset[str], proxy: _PinnedProxy | None
) -> tuple[ResolvedSourceURL, str, dict[str, Any]]:
    resolution = resolve_safe_source_url(current, allowed_private_hosts=private_hosts)
    _require_proxy_target_compatibility(proxy, resolution)
    request_url = _pinned_url(current, resolution.pinned_ip)
    return resolution, request_url, _request_extensions(resolution)


def _resolve_injected_hop(
    current: str,
) -> tuple[ResolvedSourceURL, str, dict[str, Any]]:
    parsed = _validate_url_shape(current)
    resolution = ResolvedSourceURL(
        url=current,
        host=_normalize_hostname(parsed.hostname or ""),
        scheme=parsed.scheme,
        resolved_ips=((parsed.hostname or ""),),
    )
    return resolution, current, {}


def _resolve_hop(
    transport: Any,
    current: str,
    *,
    private_hosts: frozenset[str],
    proxy: _PinnedProxy | None,
) -> tuple[ResolvedSourceURL, str, dict[str, Any]]:
    if transport is None:
        return _resolve_pinned_hop(current, private_hosts, proxy)
    return _resolve_injected_hop(current)
