"""Pinned-proxy and peer verification for the source HTTP boundary."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from ._http_resolve import _approved_private_ip, _resolve_addresses
from ._http_types import (
    _HARD_MAX_URL_CHARS,
    ResolvedSourceURL,
    SourceEgressError,
    _PinnedProxy,
)
from ._http_urls import _normalize_hostname


def _require_direct_peer(
    response: Any,
    resolution: ResolvedSourceURL,
    proxy: _PinnedProxy | None,
) -> None:
    """Verify that a direct connection reached the address selected pre-I/O."""
    if proxy is not None:
        return
    stream = response.extensions.get("network_stream")
    get_extra_info = getattr(stream, "get_extra_info", None)
    if not callable(get_extra_info):
        raise SourceEgressError("Source connection peer could not be verified")
    peer = get_extra_info("server_addr")
    try:
        peer_ip = ipaddress.ip_address(str(peer[0])).compressed
    except (IndexError, TypeError, ValueError) as exc:
        raise SourceEgressError("Source connection peer could not be verified") from exc
    if peer_ip != resolution.pinned_ip:
        raise SourceEgressError("Source connection peer did not match its DNS pin")


def _pin_configured_proxy(proxy_url: str | None) -> _PinnedProxy | None:
    """Pin an explicit TLS-profile proxy without exposing it to ambient DNS.

    HTTPS proxies are rejected because HTTPX/httpcore cannot independently set
    the proxy TLS name after replacing its hostname with the approved address.
    Plain HTTP and SOCKS proxies remain supported; their destination is pinned
    and their credentials remain runtime-only in the resolved profile.
    """
    if not proxy_url:
        return None
    if len(proxy_url) > _HARD_MAX_URL_CHARS:
        raise SourceEgressError("Configured source proxy is not safely pinnable")
    parsed = urlsplit(proxy_url)
    host = _normalize_hostname(parsed.hostname or "")
    _validate_proxy_shape(parsed, host)
    _validate_proxy_port(parsed)
    pinned_ip = _approved_private_ip(_resolve_addresses(host)[0])
    authority = _proxy_authority(parsed, pinned_ip)
    return _PinnedProxy(
        url=urlunsplit((parsed.scheme, authority, "", "", "")),
        scheme=parsed.scheme,
    )


def _validate_proxy_shape(parsed: SplitResult, host: str) -> None:
    if (
        parsed.scheme not in {"http", "socks5", "socks5h"}
        or not host
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SourceEgressError("Configured source proxy is not safely pinnable")


def _validate_proxy_port(parsed: SplitResult) -> None:
    try:
        port = parsed.port
    except ValueError as exc:
        raise SourceEgressError(
            "Configured source proxy is not safely pinnable"
        ) from exc
    if port == 0:
        raise SourceEgressError("Configured source proxy is not safely pinnable")


def _proxy_authority(parsed: SplitResult, pinned_ip: str) -> str:
    rendered_ip = (
        f"[{pinned_ip}]" if ipaddress.ip_address(pinned_ip).version == 6 else pinned_ip
    )
    userinfo = parsed.netloc.rpartition("@")[0] if "@" in parsed.netloc else ""
    authority = f"{userinfo}@{rendered_ip}" if userinfo else rendered_ip
    if parsed.port is not None:
        authority = f"{authority}:{parsed.port}"
    return authority


def _require_proxy_target_compatibility(
    proxy: _PinnedProxy | None, resolution: ResolvedSourceURL
) -> None:
    if proxy is None or proxy.scheme.startswith("socks") or resolution.scheme == "http":
        return
    try:
        ipaddress.ip_address(resolution.host)
    except ValueError as exc:
        raise SourceEgressError(
            "Configured HTTP proxy cannot safely pin this HTTPS source"
        ) from exc


def _profile_httpx_kwargs(tls: Any, proxy: _PinnedProxy | None) -> dict[str, Any]:
    """Project a TLS profile while excluding unpinnable ambient proxies."""
    kwargs: dict[str, Any] = tls.httpx_kwargs()
    # Trust anchors and mTLS are already captured in the profile SSLContext.
    # Environment-discovered proxies are not reference-resolved and cannot be
    # pinned, so this egress boundary accepts only the profile's explicit proxy.
    kwargs["trust_env"] = False
    if proxy is None:
        kwargs.pop("proxy", None)
    else:
        kwargs["proxy"] = proxy.url
    return kwargs
