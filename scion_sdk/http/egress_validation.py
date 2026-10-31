"""Operator-supplied base URL validation and DNS preflight."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import ParseResult, urlparse

from scion_sdk.http.egress_policy import _is_ip_literal

MAX_RESOLVED_ADDRESSES = 64


@dataclass(slots=True)
class EgressDecision:
    """Outcome of an egress check."""

    allowed: bool
    reason: str = ""
    resolved_ips: tuple[str, ...] = ()


_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


def _is_shared_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address in _SHARED_ADDRESS_SPACE


def egress_ip_is_blocked(ip: str, *, allow_loopback: bool) -> bool:
    """Return whether an address is outside the public egress boundary.

    This is public so connection-pinning transports can apply exactly the same
    classification to the address they connect to as the preflight DNS guard.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparsable → block
    if addr.is_loopback:
        return not allow_loopback
    # Block private, link-local, reserved, multicast, unspecified, and the cloud metadata IP.
    if (
        _is_shared_address(addr)
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    ):
        return True
    # cloud metadata service
    return str(addr) in {"169.254.169.254", "fd00:ec2::254"}


def _parsed_rejection(parsed: ParseResult) -> str:
    """The reason a parsed URL is syntactically unacceptable, or ``""``."""
    if parsed.scheme not in {"http", "https"}:
        return f"unsupported scheme: {parsed.scheme!r}"
    if parsed.username is not None or parsed.password is not None:
        return "embedded URL credentials are not allowed"
    if not parsed.hostname:
        return "missing host"
    try:
        _ = parsed.port
    except ValueError:
        return "invalid port"
    return ""


def _url_host(url: str) -> tuple[str, str]:
    """The URL's host, or ``("", reason)`` when it is syntactically unacceptable."""
    if not url or not isinstance(url, str):
        return "", "empty url"
    parsed = urlparse(url)
    reason = _parsed_rejection(parsed)
    return ("", reason) if reason else (parsed.hostname or "", "")


def validate_base_url(url: str, *, allow_loopback: bool = True) -> EgressDecision:
    """Syntactic check: scheme + host present, and an IP *literal* host is not in a blocked range.

    Does not perform DNS resolution — use :func:`validate_base_url_resolved` for that.
    """
    host, rejection = _url_host(url)
    if rejection:
        return EgressDecision(False, rejection)
    if not _is_ip_literal(host):
        return EgressDecision(True, "hostname (resolve to verify)")
    if egress_ip_is_blocked(host, allow_loopback=allow_loopback):
        return EgressDecision(False, "blocked IP literal")
    return EgressDecision(True, "allowed IP literal", (host,))


def _collect_resolved_ips(infos: Any) -> tuple[list[str], str]:
    """Unique compressed IPs from getaddrinfo answers, or a failure reason."""
    ips: list[str] = []
    for answer_count, info in enumerate(infos, start=1):
        if answer_count > MAX_RESOLVED_ADDRESSES:
            return [], "too many addresses resolved"
        try:
            rendered = ipaddress.ip_address(str(info[4][0])).compressed
        except (IndexError, TypeError, ValueError):
            return [], "invalid address resolved"
        if rendered not in ips:
            ips.append(rendered)
    return ips, ""


def validate_base_url_resolved(
    url: str, *, allow_loopback: bool = True, resolver: Callable[..., Any] | None = None
) -> EgressDecision:
    """Resolve the host and reject if **any** resolved IP is blocked.

    An allowed decision supplies normalized ``resolved_ips`` for transport
    pinning; callers must not hand the hostname to a second resolver lookup.

    ``resolver`` is injectable for tests: a callable ``host -> list[(family, ..., sockaddr)]`` matching
    :func:`socket.getaddrinfo`'s return shape (defaults to ``socket.getaddrinfo``).
    """
    syntactic = validate_base_url(url, allow_loopback=allow_loopback)
    if not syntactic.allowed:
        return syntactic
    if syntactic.resolved_ips:  # was an IP literal already validated above
        return syntactic

    host = urlparse(url).hostname or ""
    getaddrinfo = resolver or socket.getaddrinfo
    try:
        infos = getaddrinfo(host, None)
    except OSError:
        return EgressDecision(False, "DNS resolution failed")
    return _decide_resolved(infos, allow_loopback=allow_loopback)


def _decide_resolved(infos: Any, *, allow_loopback: bool) -> EgressDecision:
    ips, failure = _collect_resolved_ips(infos)
    if not failure and not ips:
        failure = "no addresses resolved"
    if not failure and any(
        egress_ip_is_blocked(ip, allow_loopback=allow_loopback) for ip in ips
    ):
        failure = "resolves to blocked address"
    if failure:
        return EgressDecision(False, failure)
    return EgressDecision(True, "all resolved IPs allowed", tuple(ips))
