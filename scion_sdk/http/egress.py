"""The SSRF policy a governed client's egress is checked against.

This is the typed policy check :func:`check_egress_destination` and the
pinned-address transport :func:`pinned_egress_transport` that
:mod:`scion_sdk.http.client` wires into ``create_http_client``
(SCION-CONNECTOR-CONTROL-R028.2); both are usable on their own by any call site
that must decide whether a destination is a permitted egress target, or must
hold a connection to an already-resolved, already-approved address.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlsplit

import anyio
import httpx

__all__ = [
    "AsyncDnsPinnedEgressTransport",
    "DnsPinnedEgressTransport",
    "EgressDecision",
    "EgressOptions",
    "EgressPolicyError",
    "PinnedAddressTransport",
    "PinnedEgressViolation",
    "check_egress_destination",
    "egress_ip_is_blocked",
    "normalize_private_hosts",
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
            compared after hostname case and trailing-dot normalization.
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
    host = host.lower().rstrip(".")
    allow_loopback = options.allow_loopback
    allowed_private_hosts = normalize_private_hosts(options.allowed_private_hosts)
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
        logical_url = request.url
        if "host" not in request.headers:
            request.headers["host"] = logical_url.netloc.decode("ascii")
        request.url = logical_url.copy_with(host=self._host, port=self._port)
        if logical_url.scheme == "https":
            request.extensions = {
                **request.extensions,
                "sni_hostname": logical_url.host,
            }
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


# --- Operator-supplied base URL guard (SCION-CONNECTOR-CONTROL-R014.5), moved from agent-utilities ---

MAX_RESOLVED_ADDRESSES = 64


@dataclass(slots=True)
class EgressDecision:
    """Outcome of an egress check."""

    allowed: bool
    reason: str = ""
    resolved_ips: tuple[str, ...] = ()


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


def _url_host(url: str) -> tuple[str, str]:
    """The URL's host, or ``("", reason)`` when it is syntactically unacceptable."""
    if not url or not isinstance(url, str):
        return "", "empty url"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "", f"unsupported scheme: {parsed.scheme!r}"
    if parsed.username is not None or parsed.password is not None:
        return "", "embedded URL credentials are not allowed"
    host = parsed.hostname
    if not host:
        return "", "missing host"
    try:
        _ = parsed.port
    except ValueError:
        return "", "invalid port"
    return host, ""


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


# --- Per-request DNS-pinned egress (SCION-CONNECTOR-CONTROL-R014.16), moved from agent-utilities ---

_ALLOWED_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # RFC 6598 shared address space: the Kubernetes pod/service CIDR.
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
)
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")
_MAX_URL_LENGTH = 8_192


class PinnedEgressViolation(httpx.TransportError):
    """An outbound request failed the DNS-pinning or peer-identity boundary."""


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


def _label_is_valid(label: str) -> bool:
    return (
        bool(label)
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(c.isalnum() or c == "-" for c in label)
    )


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _normalize_private_host(raw: object) -> str:
    host = str(raw).strip().lower().rstrip(".")
    if not host.isascii():
        raise ValueError("private egress hosts must be ASCII")
    if (
        not host
        or len(host) > 253
        or any(ord(c) < 33 for c in host)
        or any(c in host for c in "/@*?#[]")
    ):
        raise ValueError("private egress hosts must be exact hostnames")
    if not _is_ip_literal(host) and not all(
        _label_is_valid(label) for label in host.split(".")
    ):
        raise ValueError("private egress hosts must be exact hostnames")
    return host


def normalize_private_hosts(hosts: Collection[str]) -> frozenset[str]:
    """Validate the explicit private-host allow-list into exact lowercase names.

    Raises:
        ValueError: a host is not an exact ASCII hostname or IP literal (no
            wildcards, paths, credentials or brackets), or there are over 256.
    """
    normalized = {_normalize_private_host(raw) for raw in hosts}
    if len(normalized) > 256:
        raise ValueError("private egress host allowlist is too large")
    return frozenset(normalized)


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


def _resolve_pinned_request(
    request: httpx.Request,
    *,
    allowed_private_hosts: frozenset[str],
    allow_loopback: bool,
) -> tuple[str, str, tuple[str, int]]:
    """Resolve one request once and rewrite it to the chosen IP, keeping Host/SNI."""
    logical_url = request.url
    scheme, host = _checked_logical_target(logical_url)
    ips = _candidate_ips(
        logical_url,
        host,
        allowed_private_hosts=allowed_private_hosts,
        allow_loopback=allow_loopback,
    )
    pinned_ip = ips[0]
    address = ipaddress.ip_address(pinned_ip)
    if scheme == "http" and not (address.is_loopback or host in allowed_private_hosts):
        raise PinnedEgressViolation("unencrypted public egress is not permitted")

    request.headers["Host"] = logical_url.netloc.decode("ascii")
    request.url = logical_url.copy_with(host=pinned_ip)
    if scheme == "https":
        request.extensions = {**request.extensions, "sni_hostname": host}
    return (
        host,
        pinned_ip,
        (scheme, logical_url.port or (443 if scheme == "https" else 80)),
    )


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


class _PinState:
    """Shared per-transport pin bookkeeping for the sync and async transports."""

    def __init__(
        self,
        *,
        allowed_private_hosts: Collection[str],
        allow_loopback: bool,
        verify_peer: bool,
    ) -> None:
        self.allowed_private_hosts = normalize_private_hosts(allowed_private_hosts)
        self.allow_loopback = allow_loopback
        self.verify_peer = verify_peer
        self._origin_hosts: dict[tuple[str, int], str] = {}
        self._lock = threading.Lock()

    def resolve(self, request: httpx.Request) -> tuple[str, str, tuple[str, int]]:
        return _resolve_pinned_request(
            request,
            allowed_private_hosts=self.allowed_private_hosts,
            allow_loopback=self.allow_loopback,
        )

    def pin(self, request: httpx.Request) -> str:
        return self.bind(self.resolve(request))

    def bind(self, resolved: tuple[str, str, tuple[str, int]]) -> str:
        host, pinned_ip, origin = resolved
        key = (f"{origin[0]}:{pinned_ip}", origin[1])
        with self._lock:
            prior = self._origin_hosts.setdefault(key, host)
        if prior != host:
            raise PinnedEgressViolation("outbound connection reuse crossed origins")
        return pinned_ip


class _PinnedTransportBase:
    """Shared construction for the sync and async DNS-pinned transports."""

    def __init__(
        self,
        inner: Any,
        *,
        allowed_private_hosts: Collection[str] = (),
        allow_loopback: bool = False,
        verify_peer: bool = True,
    ) -> None:
        self._inner = inner
        self._state = _PinState(
            allowed_private_hosts=allowed_private_hosts,
            allow_loopback=allow_loopback,
            verify_peer=verify_peer,
        )


class DnsPinnedEgressTransport(_PinnedTransportBase, httpx.BaseTransport):
    """Resolves each request once, validates it, and dials only that address.

    Public destinations must resolve to public addresses. A host named in
    ``allowed_private_hosts`` must resolve into loopback, RFC 1918, RFC 6598 or
    IPv6 ULA space. The original name stays in ``Host`` and TLS SNI. Unless
    ``verify_peer`` is off, the connected peer must equal the pinned address.
    """

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        pinned_ip = self._state.pin(request)
        response = self._inner.handle_request(request)
        if self._state.verify_peer:
            try:
                _require_pinned_peer(response, pinned_ip)
            except Exception:
                response.close()
                raise
        return response

    def close(self) -> None:
        self._inner.close()


class AsyncDnsPinnedEgressTransport(_PinnedTransportBase, httpx.AsyncBaseTransport):
    """The asynchronous :class:`DnsPinnedEgressTransport`."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        probe = httpx.Request(
            request.method,
            request.url,
            headers=request.headers,
            extensions=request.extensions.copy(),
        )
        resolved = await anyio.to_thread.run_sync(
            self._state.resolve, probe, abandon_on_cancel=True
        )
        pinned_ip = self._state.bind(resolved)
        request.url = probe.url
        request.headers["Host"] = probe.headers["Host"]
        request.extensions = probe.extensions
        response = await self._inner.handle_async_request(request)
        if self._state.verify_peer:
            try:
                _require_pinned_peer(response, pinned_ip)
            except Exception:
                await response.aclose()
                raise
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()
