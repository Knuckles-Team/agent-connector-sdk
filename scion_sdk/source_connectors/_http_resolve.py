"""DNS resolution and private-host policy for the source HTTP boundary."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from scion_sdk.http.egress import (
    MAX_RESOLVED_ADDRESSES,
    validate_base_url,
    validate_base_url_resolved,
)

from ._http_types import _METADATA_ADDRESSES, ResolvedSourceURL, SourceEgressError
from ._http_urls import _normalize_hostname, _validate_url_shape


def _approved_private_ip(ip: str) -> str:
    """Validate an address reached through an exact private-host exception."""
    if "%" in ip:
        raise SourceEgressError("Approved source hostname resolved unsafely")
    try:
        address = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise SourceEgressError("Approved source hostname resolved unsafely") from exc
    rendered = address.compressed
    if (
        rendered in _METADATA_ADDRESSES
        or address.is_multicast
        or address.is_unspecified
        or not (
            address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
        )
    ):
        raise SourceEgressError("Approved source hostname resolved unsafely")
    return rendered


def _resolve_addresses(host: str, *, resolver: Any = None) -> tuple[str, ...]:
    getaddrinfo = resolver or socket.getaddrinfo
    try:
        answers = getaddrinfo(host, None)
    except OSError as exc:
        raise SourceEgressError("Source hostname did not resolve") from exc
    addresses: list[str] = []
    for answer_count, answer in enumerate(answers, start=1):
        if answer_count > MAX_RESOLVED_ADDRESSES:
            raise SourceEgressError("Source hostname returned too many addresses")
        try:
            rendered = str(answer[4][0])
        except (IndexError, TypeError) as exc:
            raise SourceEgressError("Source hostname resolved unsafely") from exc
        if rendered not in addresses:
            addresses.append(rendered)
    if not addresses:
        raise SourceEgressError("Source hostname did not resolve")
    return tuple(addresses)


def resolve_safe_source_url(
    url: str,
    *,
    allowed_private_hosts: Iterable[str] | None = None,
    resolver: Any = None,
) -> ResolvedSourceURL:
    """Resolve and approve one hop, returning addresses suitable for pinning.

    DNS is called exactly once here. The fetch path connects to ``pinned_ip``
    while retaining ``host`` as its HTTP authority and TLS SNI name.
    """
    allowed = normalize_allowed_hosts(allowed_private_hosts)
    parsed = _validate_url_shape(url)
    host = _normalize_hostname(parsed.hostname or "")
    syntactic = validate_base_url(url, allow_loopback=host in allowed)
    if not syntactic.allowed and host not in allowed:
        raise SourceEgressError("Source URL is not permitted by egress policy")

    if host in allowed:
        addresses = tuple(
            _approved_private_ip(ip)
            for ip in _resolve_addresses(host, resolver=resolver)
        )
    else:
        decision = validate_base_url_resolved(
            url, allow_loopback=False, resolver=resolver
        )
        if not decision.allowed or not decision.resolved_ips:
            raise SourceEgressError("Source URL is not permitted by egress policy")
        addresses = decision.resolved_ips
    return ResolvedSourceURL(
        url=url,
        host=host,
        scheme=parsed.scheme,
        resolved_ips=addresses,
    )


def normalize_allowed_hosts(hosts: Iterable[str] | None) -> frozenset[str]:
    """Normalize an exact-host allow-list; wildcards and URL-shaped entries fail."""
    normalized: set[str] = set()
    for raw in hosts or ():
        host = str(raw).strip().lower().rstrip(".")
        if not host:
            continue
        if any(ch in host for ch in ("/", "@", "*", "?", "#")):
            raise SourceEgressError(
                "Private-host allow-list entries must be exact hostnames"
            )
        normalized.add(_normalize_hostname(host))
    return frozenset(normalized)


def source_url_host(url: str) -> str:
    """Return a normalized validated hostname without doing DNS I/O."""
    _validate_url_shape(url)
    decision = validate_base_url(url, allow_loopback=False)
    if not decision.allowed:
        raise SourceEgressError("Source URL is not permitted by egress policy")
    return _normalize_hostname(urlsplit(url).hostname or "")


def require_safe_source_url(
    url: str,
    *,
    allowed_private_hosts: Iterable[str] | None = None,
    resolve_dns: bool = True,
    resolver: Any = None,
) -> str:
    """Validate one source URL and return its normalized hostname.

    ``allowed_private_hosts`` is exact-match only. It is the explicit operator
    escape hatch for approved intranet sources; it does not permit arbitrary
    private IPs, wildcard domains, embedded credentials, or alternate schemes.
    """
    allowed = normalize_allowed_hosts(allowed_private_hosts)
    parsed = _validate_url_shape(url)
    host = _normalize_hostname(parsed.hostname or "")

    # Always perform syntax/IP-literal validation. An explicitly approved host
    # may be private, but it still cannot carry userinfo or an invalid scheme.
    syntactic = validate_base_url(url, allow_loopback=host in allowed)
    if not syntactic.allowed and host not in allowed:
        raise SourceEgressError("Source URL is not permitted by egress policy")
    if not resolve_dns:
        return host
    return resolve_safe_source_url(
        url,
        allowed_private_hosts=allowed,
        resolver=resolver,
    ).host
