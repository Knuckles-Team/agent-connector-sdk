"""DNS-pinned egress: resolve each request once and connect to the vetted address.

A hostname check before the request is not enough against DNS rebinding: the
connection would resolve the name again and may reach a different, private
address. :func:`pin_request` resolves once, applies the boundary to every
answer, and rewrites the request to the chosen address while keeping the
logical ``Host`` header and TLS server name, so the connection can only reach
the address that was checked.

Public hosts must resolve only to public addresses (loopback when
``allow_loopback``). A host in ``allowed_private_hosts`` must resolve only to
loopback, RFC 1918, RFC 6598 (cluster CGNAT) or IPv6 ULA addresses; an
allowlisted name that resolves to a public address is refused too.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from agent_connector_sdk.config import normalize_http_host_allowlist
from agent_connector_sdk.http.egress import (
    Resolver,
    egress_ip_is_blocked,
    resolve_host,
)

__all__ = ["EgressPolicy", "Pin", "PinnedEgressViolation", "pin_request"]

_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "fc00::/7",
    )
)
_MAX_URL = 8_192


class PinnedEgressViolation(httpx.TransportError):
    """A request failed the DNS-pinning or peer-identity boundary."""


@dataclass(frozen=True)
class EgressPolicy:
    """Pin every request of a governed client to a checked address.

    Attributes:
        allowed_private_hosts: Exact hostnames that may (and must) resolve to
            private addresses.
        allow_loopback: Public-host requests may reach loopback addresses.
        verify_peer: Check that the connected peer is the pinned address.
            Disable only for an in-process test transport.
    """

    allowed_private_hosts: frozenset[str] = field(default_factory=frozenset)
    allow_loopback: bool = False
    verify_peer: bool = True

    def __post_init__(self) -> None:
        hosts = frozenset(
            normalize_http_host_allowlist(list(self.allowed_private_hosts))
        )
        object.__setattr__(self, "allowed_private_hosts", hosts)

    @classmethod
    def for_hosts(cls, hosts: Iterable[str], **kwargs: bool) -> EgressPolicy:
        """A policy allowlisting ``hosts`` as private destinations."""
        return cls(allowed_private_hosts=frozenset(hosts), **kwargs)


@dataclass(frozen=True)
class Pin:
    """Where one request was pinned: its logical host, address and origin."""

    host: str
    address: str
    origin: tuple[str, int]


def _private(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_loopback or any(ip in network for network in _PRIVATE_NETWORKS)


def _addresses(host: str, policy: EgressPolicy, resolver: Resolver | None) -> str:
    decision = resolve_host(host, resolver=resolver)
    if not decision.allowed:
        raise PinnedEgressViolation(f"outbound DNS: {decision.reason}")
    addresses = decision.resolved_ips
    if host in policy.allowed_private_hosts:
        outside = not all(_private(address) for address in addresses)
    else:
        outside = any(
            egress_ip_is_blocked(address, allow_loopback=policy.allow_loopback)
            for address in addresses
        )
    if outside:
        raise PinnedEgressViolation("outbound destination is outside its boundary")
    return addresses[0]


def _logical_host(request: httpx.Request) -> tuple[str, str]:
    url = request.url
    scheme = url.scheme.lower()
    host = (url.host or "").lower().rstrip(".")
    parts = urlsplit(str(url))
    if (
        len(str(url)) > _MAX_URL
        or scheme not in {"http", "https"}
        or not host
        or parts.username is not None
        or parts.password is not None
    ):
        raise PinnedEgressViolation("outbound URL was rejected")
    return scheme, host


def pin_request(
    request: httpx.Request, policy: EgressPolicy, resolver: Resolver | None = None
) -> Pin:
    """Resolve ``request``'s host once and rewrite it to the checked address.

    Raises:
        PinnedEgressViolation: the URL, resolution or any resolved address is
            outside the policy, or plaintext HTTP would leave a private boundary.
    """
    scheme, host = _logical_host(request)
    address = _addresses(host, policy, resolver)
    if scheme == "http" and not _private(address):
        raise PinnedEgressViolation("unencrypted public egress is not permitted")
    authority = request.url.netloc.decode("ascii")
    request.url = request.url.copy_with(host=address)
    request.headers["Host"] = authority
    if scheme == "https":
        request.extensions = {**request.extensions, "sni_hostname": host}
    port = request.url.port or (443 if scheme == "https" else 80)
    return Pin(host, address, (scheme, port))
