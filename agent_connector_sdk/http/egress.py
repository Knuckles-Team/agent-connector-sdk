"""Egress (SSRF) checks for URLs a connector did not configure itself.

Use before following an operator- or API-supplied URL (upload sessions,
webhooks, redirects to another host). :func:`validate_egress_url` is syntactic;
:func:`validate_resolved_egress_url` also resolves the host and rejects when any
address is private, link-local, reserved, multicast, unspecified or a cloud
metadata endpoint. An allowed resolved decision lists the addresses: connect to
one of those (keeping the logical host for TLS) rather than resolving again.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

__all__ = [
    "MAX_RESOLVED_ADDRESSES",
    "EgressDecision",
    "egress_ip_is_blocked",
    "resolve_host",
    "validate_egress_url",
    "validate_resolved_egress_url",
]

#: Resolution answers beyond this are refused rather than truncated.
MAX_RESOLVED_ADDRESSES = 64
_METADATA_ADDRESSES = frozenset({"169.254.169.254", "fd00:ec2::254"})
Resolver = Callable[[str, Any], Sequence[Any]]


@dataclass(frozen=True, slots=True)
class EgressDecision:
    """Whether a URL may be reached, why, and the addresses that were checked."""

    allowed: bool
    reason: str = ""
    resolved_ips: tuple[str, ...] = ()


def egress_ip_is_blocked(ip: str, *, allow_loopback: bool) -> bool:
    """Whether ``ip`` is outside the public egress boundary (unparsable blocks)."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if address.is_loopback:
        return not allow_loopback
    return (
        address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        or address.compressed in _METADATA_ADDRESSES
    )


def _syntax_problem(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        return f"unsupported scheme: {parts.scheme!r}"
    if parts.username is not None or parts.password is not None:
        return "embedded URL credentials are not allowed"
    if not parts.hostname:
        return "missing host"
    try:
        _ = parts.port
    except ValueError:
        return "invalid port"
    return None


def validate_egress_url(url: str, *, allow_loopback: bool = True) -> EgressDecision:
    """Scheme, credentials, host and port, and an IP-literal host's range."""
    if not url:
        return EgressDecision(False, "empty url")
    problem = _syntax_problem(url)
    if problem is not None:
        return EgressDecision(False, problem)
    host = urlsplit(url).hostname or ""
    try:
        literal = ipaddress.ip_address(host).compressed
    except ValueError:
        return EgressDecision(True, "hostname (resolve to verify)")
    if egress_ip_is_blocked(literal, allow_loopback=allow_loopback):
        return EgressDecision(False, "blocked IP literal")
    return EgressDecision(True, "allowed IP literal", (literal,))


def resolve_host(host: str, *, resolver: Resolver | None = None) -> EgressDecision:
    """Resolve ``host`` once, bounded; the decision lists every distinct address.

    Refused when resolution fails, returns nothing, returns more than
    :data:`MAX_RESOLVED_ADDRESSES` answers or an unparsable address. No range
    check: callers apply their own boundary to ``resolved_ips``.
    """
    try:
        answers = (resolver or socket.getaddrinfo)(host, None)
    except OSError:
        return EgressDecision(False, "DNS resolution failed")
    if len(answers) > MAX_RESOLVED_ADDRESSES:
        return EgressDecision(False, "too many addresses resolved")
    addresses: list[str] = []
    for answer in answers:
        try:
            addresses.append(ipaddress.ip_address(str(answer[4][0])).compressed)
        except (IndexError, TypeError, ValueError):
            return EgressDecision(False, "invalid address resolved")
    unique = tuple(dict.fromkeys(addresses))
    if not unique:
        return EgressDecision(False, "no addresses resolved")
    return EgressDecision(True, "resolved", unique)


def validate_resolved_egress_url(
    url: str, *, allow_loopback: bool = True, resolver: Resolver | None = None
) -> EgressDecision:
    """:func:`validate_egress_url`, then every resolved address must be allowed.

    ``resolver`` has :func:`socket.getaddrinfo`'s shape (tests inject one).
    """
    decision = validate_egress_url(url, allow_loopback=allow_loopback)
    if not decision.allowed or decision.resolved_ips:
        return decision
    resolved = resolve_host(urlsplit(url).hostname or "", resolver=resolver)
    if not resolved.allowed:
        return resolved
    addresses = resolved.resolved_ips
    if any(egress_ip_is_blocked(ip, allow_loopback=allow_loopback) for ip in addresses):
        return EgressDecision(False, "resolves to blocked address")
    return EgressDecision(True, "all resolved addresses allowed", addresses)
