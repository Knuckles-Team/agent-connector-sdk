"""The SSRF policy a governed client's egress is checked against.

This is the typed policy check :func:`check_egress_destination` and the
pinned-address transport :func:`pinned_egress_transport` that
:mod:`agent_connector_sdk.http.client` wires into ``create_http_client``
(SDK-CONNECTOR-CONTROL-R028.2); both are usable on their own by any call site
that must decide whether a destination is a permitted egress target, or must
hold a connection to an already-resolved, already-approved address.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Collection
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

__all__ = [
    "EgressDecision",
    "EgressOptions",
    "EgressPolicyError",
    "PinnedAddressTransport",
    "check_egress_destination",
    "egress_ip_is_blocked",
    "pinned_egress_transport",
    "validate_base_url",
    "validate_base_url_resolved",
]


class EgressPolicyError(ValueError):
    """``host`` is not a permitted egress destination under this policy."""


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _is_private(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private and not address.is_loopback


@dataclass(frozen=True)
class EgressOptions:
    """The knobs of the egress policy; the defaults enforce it strictly.

    Attributes:
        pin_egress: When ``False``, the policy is not enforced at all (an
            explicit, named escape hatch; the default enforces it).
        allowed_private_hosts: Private-network hosts this policy allows,
            compared exactly against ``host``.
        allow_loopback: Permit a loopback destination (``127.0.0.1``,
            ``::1``, ``localhost``).
    """

    pin_egress: bool = True
    allowed_private_hosts: Collection[str] = ()
    allow_loopback: bool = False


_STRICT_EGRESS = EgressOptions()


def check_egress_destination(
    host: str, options: EgressOptions = _STRICT_EGRESS
) -> None:
    """Reject ``host`` unless the policy explicitly allows it.

    Args:
        host: The outbound request's destination hostname or address.
        options: The :class:`EgressOptions` policy; strict by default.

    Raises:
        EgressPolicyError: ``host`` is loopback or a private-network address
            and not named by ``allowed_private_hosts`` or ``allow_loopback``.
    """
    if not options.pin_egress:
        return
    allow_loopback = options.allow_loopback
    allowed_private_hosts = options.allowed_private_hosts
    if _is_loopback(host):
        if not allow_loopback and host not in allowed_private_hosts:
            raise EgressPolicyError(f"loopback destination is not permitted: {host}")
        return
    if _is_private(host) and host not in allowed_private_hosts:
        raise EgressPolicyError(f"private-network destination is not permitted: {host}")


class PinnedAddressTransport(httpx.BaseTransport):
    """Wraps ``inner``, always dialing the resolved ``host``/``port`` it was built with.

    Performs no address resolution itself, so a request handled through this
    transport never re-resolves DNS: every request reuses the address it was
    constructed with, even if the request's own URL names a different host.
    The original hostname is preserved in the ``Host`` header so TLS SNI and
    virtual-host routing still see the originally requested name.
    """

    def __init__(self, inner: httpx.BaseTransport, *, host: str, port: int) -> None:
        self._inner = inner
        self._host = host
        self._port = port

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Rewrite ``request`` to the pinned address and delegate to ``inner``."""
        if "host" not in request.headers:
            request.headers["host"] = request.url.host
        request.url = request.url.copy_with(host=self._host, port=self._port)
        return self._inner.handle_request(request)

    def close(self) -> None:
        """Close the wrapped transport."""
        self._inner.close()


def pinned_egress_transport(
    *, host: str, port: int, inner: httpx.BaseTransport | None = None
) -> PinnedAddressTransport:
    """A transport pinned to an already-resolved, already policy-checked address.

    Args:
        host: The resolved address to dial for every request (not re-resolved).
        port: The resolved port to dial.
        inner: The transport that actually sends the request; a plain
            :class:`httpx.HTTPTransport` when omitted.
    """
    return PinnedAddressTransport(inner or httpx.HTTPTransport(), host=host, port=port)


# --- Operator-supplied base URL guard (SDK-CONNECTOR-CONTROL-R014.5), moved from agent-utilities ---

MAX_RESOLVED_ADDRESSES = 64


@dataclass(slots=True)
class EgressDecision:
    """Outcome of an egress check."""

    allowed: bool
    reason: str = ""
    resolved_ips: tuple[str, ...] = ()


def egress_ip_is_blocked(ip: str, *, allow_loopback: bool) -> bool:
    """Return whether an address is outside the public egress boundary.

    This is public so connection-pinning transports can apply exactly the same
    classification to the address they connect to as the preflight DNS guard.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable → block
    if addr.is_loopback:
        return not allow_loopback
    # Block private, link-local, reserved, multicast, unspecified, and the cloud metadata IP.
    if (
        addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    ):
        return True
    # cloud metadata service
    return str(addr) in {"169.254.169.254", "fd00:ec2::254"}


def validate_base_url(url: str, *, allow_loopback: bool = True) -> EgressDecision:
    """Syntactic check: scheme + host present, and an IP *literal* host is not in a blocked range.

    Does not perform DNS resolution — use :func:`validate_base_url_resolved` for that.
    """
    if not url or not isinstance(url, str):
        return EgressDecision(False, "empty url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return EgressDecision(False, f"unsupported scheme: {parsed.scheme!r}")
    if parsed.username is not None or parsed.password is not None:
        return EgressDecision(False, "embedded URL credentials are not allowed")
    host = parsed.hostname
    if not host:
        return EgressDecision(False, "missing host")
    try:
        _ = parsed.port
    except ValueError:
        return EgressDecision(False, "invalid port")
    # If the host is an IP literal, check it directly.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return EgressDecision(True, "hostname (resolve to verify)")
    if egress_ip_is_blocked(host, allow_loopback=allow_loopback):
        return EgressDecision(False, "blocked IP literal")
    return EgressDecision(True, "allowed IP literal", (host,))


def validate_base_url_resolved(
    url: str, *, allow_loopback: bool = True, resolver=None
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
    ips: list[str] = []
    for answer_count, info in enumerate(infos, start=1):
        if answer_count > MAX_RESOLVED_ADDRESSES:
            return EgressDecision(False, "too many addresses resolved")
        try:
            sockaddr = info[4]
            rendered = ipaddress.ip_address(str(sockaddr[0])).compressed
        except (IndexError, TypeError, ValueError):
            return EgressDecision(False, "invalid address resolved")
        if rendered not in ips:
            ips.append(rendered)
    if not ips:
        return EgressDecision(False, "no addresses resolved")
    for ip in ips:
        if egress_ip_is_blocked(ip, allow_loopback=allow_loopback):
            return EgressDecision(False, "resolves to blocked address")
    return EgressDecision(True, "all resolved IPs allowed", tuple(ips))
