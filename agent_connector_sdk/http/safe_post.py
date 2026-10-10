"""An SSRF-checked JSON POST helper for connectors that submit data.

:func:`create_http_client` governs the client-wide transport (timeouts, TLS,
retries); :func:`safe_post_json` adds a per-call destination check for a
connector that must POST to a self-hosted or private-network endpoint
(SDK-CONNECTOR-CONTROL-R033), mirroring the private-host allowance a GET-style
call already has, instead of dropping to an unchecked client.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

__all__ = ["NonJsonResponseError", "SsrfBlockedError", "safe_post_json"]


class SsrfBlockedError(RuntimeError):
    """The destination resolves to a private or loopback address, unapproved."""


class NonJsonResponseError(RuntimeError):
    """The response body was not valid JSON."""


def _is_private_or_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def safe_post_json(
    client: httpx.Client,
    url: str,
    json: Mapping[str, Any],
    *,
    allowed_private_hosts: frozenset[str] = frozenset(),
) -> Any:
    """POST ``json`` to ``url`` through ``client``, parsed JSON on success.

    Args:
        client: an already-governed client (see :func:`create_http_client`).
        url: the absolute request URL.
        json: the JSON-serializable request body.
        allowed_private_hosts: hostnames explicitly approved to receive a
            private or loopback destination; every other private/loopback
            host is rejected before the request is sent.

    Raises:
        SsrfBlockedError: the destination host is private or loopback and not
            named in ``allowed_private_hosts``.
        NonJsonResponseError: the response body was not valid JSON.
    """
    host = urlsplit(url).hostname or ""
    if _is_private_or_loopback(host) and host not in allowed_private_hosts:
        raise SsrfBlockedError(f"private/loopback destination is not allowed: {host}")
    response = client.post(url, json=dict(json))
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as error:
        raise NonJsonResponseError("response body was not valid JSON") from error
