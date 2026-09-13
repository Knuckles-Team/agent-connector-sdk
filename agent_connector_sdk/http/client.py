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
* retries under its :class:`~agent_connector_sdk.http.retry.RetryPolicy` and logs
  each attempt to the ``agent_connector_sdk.http`` logger with secrets redacted;
* rejects credential-bearing default headers: credentials go through ``auth``.

The options are :class:`~agent_connector_sdk.http.options.HttpClientOptions`.
"""

from __future__ import annotations

import logging
import ssl
from typing import Any
from urllib.parse import urlsplit

import httpx

from agent_connector_sdk._version import __version__
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.redaction import redact_url
from agent_connector_sdk.http.transport import AsyncGovernedTransport, GovernedTransport

__all__ = [
    "HTTP_LOGGER_NAME",
    "create_async_http_client",
    "create_http_client",
    "default_ssl_context",
]

#: The logger every governed client writes request records to.
HTTP_LOGGER_NAME = "agent_connector_sdk.http"

_logger = logging.getLogger(HTTP_LOGGER_NAME)


def default_ssl_context() -> ssl.SSLContext:
    """The platform trust store, hostname verification and TLS 1.2 or later."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _transport_kwargs(options: HttpClientOptions) -> dict[str, Any]:
    tls = options.tls
    kwargs: dict[str, Any] = {
        "verify": tls.ssl_context if tls else default_ssl_context(),
        "proxy": tls.proxy_url if tls else None,
    }
    if options.limits is not None:
        kwargs["limits"] = options.limits
    return kwargs


def _client_kwargs(options: HttpClientOptions) -> dict[str, Any]:
    if urlsplit(options.base_url).scheme == "http":
        _logger.warning(
            "plaintext HTTP client for %s: requests and credentials are not encrypted",
            redact_url(options.base_url),
        )
    return {
        "base_url": options.base_url,
        "timeout": options.timeout,
        "auth": options.auth,
        "headers": {
            "User-Agent": f"agent-connector-sdk/{__version__}",
            **options.headers,
        },
        "trust_env": False,
        "follow_redirects": False,
    }


def create_http_client(
    options: HttpClientOptions, *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """A synchronous governed client.

    ``transport`` replaces the network transport (tests); it is still wrapped
    by the retrying, logging transport, and the TLS profile does not apply to it.
    """
    inner = transport or httpx.HTTPTransport(**_transport_kwargs(options))
    governed = GovernedTransport(inner, policy=options.retry, logger=_logger)
    return httpx.Client(transport=governed, **_client_kwargs(options))


def create_async_http_client(
    options: HttpClientOptions, *, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """An asynchronous governed client; see :func:`create_http_client`."""
    inner = transport or httpx.AsyncHTTPTransport(**_transport_kwargs(options))
    governed = AsyncGovernedTransport(inner, policy=options.retry, logger=_logger)
    return httpx.AsyncClient(transport=governed, **_client_kwargs(options))
