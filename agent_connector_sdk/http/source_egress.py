"""Fail-closed source URL configuration checks.

These checks perform no DNS resolution. The connector transport must resolve and
pin the peer immediately before I/O; a configuration precheck is not an egress
authorization for a later connection.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

from agent_connector_sdk.http.egress import egress_ip_is_blocked

__all__ = ["SourceEgressError", "normalize_allowed_hosts", "require_safe_source_url"]

_MAX_URL_CHARS = 8_192


class SourceEgressError(ValueError):
    """A configured source URL or private-host exception is invalid."""


def _normalize_host(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if not candidate or "%" in candidate:
        raise SourceEgressError("Source hostname is not permitted by egress policy")
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        pass
    try:
        rendered = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SourceEgressError(
            "Source hostname is not permitted by egress policy"
        ) from exc
    labels = rendered.split(".")
    if (
        len(rendered) > 253
        or any(not label or len(label) > 63 for label in labels)
        or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-._" for ch in rendered)
    ):
        raise SourceEgressError("Source hostname is not permitted by egress policy")
    return rendered


def normalize_allowed_hosts(hosts: Iterable[str] | None) -> frozenset[str]:
    """Normalize exact host exceptions; reject wildcards and URL-like entries."""
    normalized: set[str] = set()
    for raw in hosts or ():
        host = str(raw).strip().lower().rstrip(".")
        if not host:
            continue
        if any(ch in host for ch in ("/", "@", "*", "?", "#")):
            raise SourceEgressError(
                "Private-host allow-list entries must be exact hostnames"
            )
        normalized.add(_normalize_host(host))
    return frozenset(normalized)


def require_safe_source_url(
    url: str, *, allowed_private_hosts: Iterable[str] | None = None
) -> str:
    """Validate URL shape and IP literals without resolving a hostname.

    This is for configuration admission. A network client must separately pin
    the resolved address and verify its connected peer for every request.
    """
    allowed = normalize_allowed_hosts(allowed_private_hosts)
    if (
        not isinstance(url, str)
        or not url
        or len(url) > _MAX_URL_CHARS
        or "\\" in url
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in url)
    ):
        raise SourceEgressError("Source URL is not permitted by egress policy")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise SourceEgressError("Source URL is not permitted by egress policy") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
    ):
        raise SourceEgressError("Source URL is not permitted by egress policy")
    host = _normalize_host(parsed.hostname)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    if host not in allowed and egress_ip_is_blocked(host, allow_loopback=False):
        raise SourceEgressError("Source URL is not permitted by egress policy")
    return host
