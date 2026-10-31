"""Per-request resolution helpers for the DNS-pinned egress transports."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from scion_sdk.http.egress_policy import (
    EgressOptions,
    EgressPolicyError,
    PinnedEgressViolation,
    check_egress_destination,
    normalize_private_hosts,
)
from scion_sdk.http.egress_validation import (
    _SHARED_ADDRESS_SPACE,
    _collect_resolved_ips,
    egress_ip_is_blocked,
    validate_base_url_resolved,
)

_ALLOWED_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # RFC 6598 shared address space: the Kubernetes pod/service CIDR.
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
)


_MAX_URL_LENGTH = 8_192


def _is_allowed_private_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Loopback, RFC 1918, RFC 6598 or IPv6 ULA: the private-host boundary."""
    return address.is_loopback or any(
        address in network for network in _ALLOWED_PRIVATE_NETWORKS
    )


def _check_pinned_base_host(host: str, options: EgressOptions) -> None:
    """Reject a known unsafe base host without performing DNS resolution."""
    normalized = host.lower().rstrip(".")
    allowed = normalize_private_hosts(options.allowed_private_hosts)
    try:
        check_egress_destination(
            normalized,
            EgressOptions(
                pin_egress=options.pin_egress,
                allowed_private_hosts=allowed,
                allow_loopback=options.allow_loopback,
            ),
        )
    except EgressPolicyError as exc:
        raise PinnedEgressViolation("outbound destination was rejected") from exc
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return
    if normalized in allowed:
        rejected = not _is_allowed_private_address(address)
    else:
        rejected = egress_ip_is_blocked(
            normalized, allow_loopback=options.allow_loopback
        )
        rejected |= address in _SHARED_ADDRESS_SPACE
    if rejected:
        raise PinnedEgressViolation("outbound destination was rejected")


def _resolve_private_host(host: str, port: int | None) -> list[str]:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise PinnedEgressViolation("outbound DNS resolution failed") from exc
    ips, failure = _collect_resolved_ips(answers)
    if failure:
        raise PinnedEgressViolation(
            "outbound DNS result exceeded its boundary"
            if failure.startswith("too many")
            else "outbound DNS result was invalid"
        )
    if not ips:
        raise PinnedEgressViolation("outbound DNS resolution returned no address")
    if any(not _is_allowed_private_address(ipaddress.ip_address(ip)) for ip in ips):
        raise PinnedEgressViolation(
            "configured private host resolved outside the private boundary"
        )
    return ips


def _checked_logical_target(logical_url: httpx.URL) -> tuple[str, str]:
    """The (scheme, host) of a request URL that passed the syntactic boundary."""
    if len(str(logical_url)) > _MAX_URL_LENGTH:
        raise PinnedEgressViolation("outbound URL exceeded its security boundary")
    scheme = logical_url.scheme.lower()
    host = (logical_url.host or "").lower().rstrip(".")
    if scheme not in {"http", "https"} or not host:
        raise PinnedEgressViolation("outbound URL was rejected")
    parsed = urlsplit(str(logical_url))
    if parsed.username is not None or parsed.password is not None:
        raise PinnedEgressViolation("embedded outbound credentials are not permitted")
    return scheme, host


def _candidate_ips(
    logical_url: httpx.URL,
    host: str,
    *,
    allowed_private_hosts: frozenset[str],
    allow_loopback: bool,
) -> list[str]:
    """Resolve ``host`` under the private-host or public-destination policy."""
    if host in allowed_private_hosts:
        return _resolve_private_host(host, logical_url.port)
    decision = validate_base_url_resolved(
        str(logical_url), allow_loopback=allow_loopback
    )
    if not decision.allowed or not decision.resolved_ips:
        raise PinnedEgressViolation("outbound destination was rejected")
    ips = list(decision.resolved_ips)
    if any(ipaddress.ip_address(ip) in _SHARED_ADDRESS_SPACE for ip in ips):
        raise PinnedEgressViolation("outbound destination was rejected")
    return ips


def _require_pinned_peer(response: httpx.Response, pinned_ip: str) -> None:
    stream = response.extensions.get("network_stream")
    get_extra_info = getattr(stream, "get_extra_info", None)
    if not callable(get_extra_info):
        raise PinnedEgressViolation("outbound peer identity was unavailable")
    peer = get_extra_info("server_addr")
    try:
        peer_ip = ipaddress.ip_address(str(peer[0])).compressed
    except (IndexError, TypeError, ValueError) as exc:
        raise PinnedEgressViolation("outbound peer identity was invalid") from exc
    if peer_ip != pinned_ip:
        raise PinnedEgressViolation("outbound peer did not match its DNS pin")
