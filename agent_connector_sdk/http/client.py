"""Build governed ``httpx`` clients for a connector's vendor API.

Every client built here:

* has a finite timeout (30 seconds unless configured);
* verifies certificates and hostnames through a
  :class:`~agent_connector_sdk.tls.profile.ResolvedTLSProfile`, or the platform
  trust store with TLS 1.2 or later when no profile is given;
* refuses plaintext HTTP to anything but loopback unless ``allow_plaintext`` is
  set, and logs a warning when it is;
* never reads proxies from the ambient environment (the TLS profile decides);
* does not follow redirects;
* isolates cookies for API-key authenticated clients;
* retries under its :class:`~agent_connector_sdk.http.retry.RetryPolicy` and logs
  each attempt to the ``agent_connector_sdk.http`` logger with secrets redacted;
* with ``pin_egress``, resolves each request once, refuses non-public
  destinations (except ``allowed_private_hosts``) and dials only that address;
* rejects credential-bearing default headers: credentials go through ``auth``;
* enforces ``AIRGAP_MODE`` before either transport sends a request.

The options are :class:`~agent_connector_sdk.http.options.HttpClientOptions`.
"""

from __future__ import annotations

import ipaddress
import logging
import ssl
from typing import Any
from urllib.parse import urlsplit

import httpx

from agent_connector_sdk._version import __version__
from agent_connector_sdk.auth.static import ApiKeyAuth
from agent_connector_sdk.config import setting
from agent_connector_sdk.http.egress import (
    AsyncDnsPinnedEgressTransport,
    DnsPinnedEgressTransport,
    EgressOptions,
    _check_pinned_base_host,
)
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.redaction import redact_url
from agent_connector_sdk.http.transport import AsyncGovernedTransport, GovernedTransport

__all__ = [
    "HTTP_LOGGER_NAME",
    "AirgapViolation",
    "create_async_http_client",
    "create_http_client",
    "default_ssl_context",
    "standard_headers",
]

#: The logger every governed client writes request records to.
HTTP_LOGGER_NAME = "agent_connector_sdk.http"

_logger = logging.getLogger(HTTP_LOGGER_NAME)


def default_ssl_context() -> ssl.SSLContext:
    """The platform trust store, hostname verification and TLS 1.2 or later."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def isolates_cookies(auth: httpx.Auth | None) -> bool:
    """Whether ``auth`` is an API-key identity whose client must not keep cookies."""
    return isinstance(auth, ApiKeyAuth) or bool(
        getattr(auth, "isolates_cookies", False)
    )


def _transport_kwargs(options: HttpClientOptions) -> dict[str, Any]:
    tls = options.tls
    kwargs: dict[str, Any] = {
        "verify": tls.ssl_context if tls else default_ssl_context(),
        "proxy": tls.proxy_url if tls else None,
    }
    if options.limits is not None:
        kwargs["limits"] = options.limits
    return kwargs


def standard_headers() -> dict[str, str]:
    """Return the SDK's standard request headers."""
    return {"User-Agent": f"agent-connector-sdk/{__version__}"}


def _client_kwargs(options: HttpClientOptions) -> dict[str, Any]:
    if urlsplit(options.base_url).scheme == "http":
        _logger.warning(
            "plaintext HTTP client for %s: requests and credentials are not encrypted",
            redact_url(options.base_url),
        )
    headers = httpx.Headers(standard_headers())
    headers.update(options.headers)
    return {
        "base_url": options.base_url,
        "timeout": options.timeout,
        "auth": options.auth,
        "headers": headers,
        "trust_env": False,
        "follow_redirects": False,
    }


def _check_base_host(options: HttpClientOptions) -> None:
    if options.pin_egress:
        _check_pinned_base_host(
            urlsplit(options.base_url).hostname or "",
            EgressOptions(
                allowed_private_hosts=options.allowed_private_hosts,
                allow_loopback=options.allow_loopback,
            ),
        )


class AirgapViolation(RuntimeError):
    """A request or proxy is outside the air-gap network boundary."""


_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


def _airgap_local(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return any(address in network for network in _LOCAL_NETWORKS)


def _check_airgap(request: httpx.Request, proxy: str | None) -> None:
    mode = str(setting("AIRGAP_MODE", "") or "").strip().lower()
    if mode in {"", "0", "false", "no", "off", "n", "f"}:
        return
    if mode not in {"1", "true", "yes", "on", "y", "t"}:
        raise AirgapViolation("air-gap mode configuration is invalid")
    if proxy is not None or not _airgap_local(request.url.host):
        raise AirgapViolation("air-gap mode refused a non-local destination or proxy")


class _AirgapTransport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport, proxy: str | None) -> None:
        self._inner = inner
        self._proxy = proxy

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        _check_airgap(request, self._proxy)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class _AsyncAirgapTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport, proxy: str | None) -> None:
        self._inner = inner
        self._proxy = proxy

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        _check_airgap(request, self._proxy)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def create_http_client(
    options: HttpClientOptions, *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """A synchronous governed client.

    ``transport`` replaces the network transport (tests); it is still wrapped
    by the retrying, logging transport, and the TLS profile does not apply to it.
    """
    _check_base_host(options)
    inner = transport or httpx.HTTPTransport(**_transport_kwargs(options))
    governed: httpx.BaseTransport = GovernedTransport(
        inner,
        policy=options.retry,
        logger=_logger,
        isolate_cookies=isolates_cookies(options.auth),
    )
    if options.pin_egress:
        governed = DnsPinnedEgressTransport(
            governed,
            allowed_private_hosts=options.allowed_private_hosts,
            allow_loopback=options.allow_loopback,
            verify_peer=options.verify_pinned_peer,
        )
    proxy = options.tls.proxy_url if options.tls else None
    return httpx.Client(
        transport=_AirgapTransport(governed, proxy), **_client_kwargs(options)
    )


def create_async_http_client(
    options: HttpClientOptions, *, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """An asynchronous governed client; see :func:`create_http_client`."""
    _check_base_host(options)
    inner = transport or httpx.AsyncHTTPTransport(**_transport_kwargs(options))
    governed: httpx.AsyncBaseTransport = AsyncGovernedTransport(
        inner,
        policy=options.retry,
        logger=_logger,
        isolate_cookies=isolates_cookies(options.auth),
    )
    if options.pin_egress:
        governed = AsyncDnsPinnedEgressTransport(
            governed,
            allowed_private_hosts=options.allowed_private_hosts,
            allow_loopback=options.allow_loopback,
            verify_peer=options.verify_pinned_peer,
        )
    proxy = options.tls.proxy_url if options.tls else None
    return httpx.AsyncClient(
        transport=_AsyncAirgapTransport(governed, proxy), **_client_kwargs(options)
    )
