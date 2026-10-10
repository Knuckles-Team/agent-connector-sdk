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
from collections.abc import Collection

import httpx

__all__ = [
    "EgressPolicyError",
    "PinnedAddressTransport",
    "check_egress_destination",
    "pinned_egress_transport",
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


def check_egress_destination(
    host: str,
    *,
    pin_egress: bool = True,
    allowed_private_hosts: Collection[str] = (),
    allow_loopback: bool = False,
) -> None:
    """Reject ``host`` unless the policy explicitly allows it.

    Args:
        host: The outbound request's destination hostname or address.
        pin_egress: When ``False``, the policy is not enforced at all (an
            explicit, named escape hatch; the default enforces it).
        allowed_private_hosts: Private-network hosts this policy allows,
            compared exactly against ``host``.
        allow_loopback: Permit a loopback destination (``127.0.0.1``,
            ``::1``, ``localhost``).

    Raises:
        EgressPolicyError: ``host`` is loopback or a private-network address
            and not named by ``allowed_private_hosts`` or ``allow_loopback``.
    """
    if not pin_egress:
        return
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
