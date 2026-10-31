"""A transport pinned to one already-resolved address."""

from __future__ import annotations

import httpx


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
