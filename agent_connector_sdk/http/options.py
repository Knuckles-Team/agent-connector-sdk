"""How a governed client reaches one API, validated when it is built."""

from __future__ import annotations

import ipaddress
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from agent_connector_sdk.http.redaction import is_sensitive_name
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.tls.profile import ResolvedTLSProfile

__all__ = ["DEFAULT_TIMEOUT_SECONDS", "HttpClientOptions"]

#: Default request timeout in seconds.
DEFAULT_TIMEOUT_SECONDS = 30.0


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _base_url_problem(base_url: str) -> str | None:
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return "base_url must be an absolute http or https URL"
    if parts.username or parts.password:
        return "base_url must not carry credentials; use auth"
    return None


def _timeout_problem(timeout: float | httpx.Timeout) -> str | None:
    values = (
        [timeout.connect, timeout.read, timeout.write, timeout.pool]
        if isinstance(timeout, httpx.Timeout)
        else [timeout]
    )
    finite = all(v is not None and math.isfinite(v) and v > 0 for v in values)
    return None if finite else "timeout must be finite and positive"


def _plaintext_problem(base_url: str, allow_plaintext: bool) -> str | None:
    parts = urlsplit(base_url)
    if parts.scheme != "http" or _is_loopback(parts.hostname or "") or allow_plaintext:
        return None
    return "plaintext http requires allow_plaintext"


@dataclass(frozen=True)
class HttpClientOptions:
    """How a governed client reaches one API.

    Attributes:
        base_url: The API root; relative request URLs resolve against it.
        timeout: Seconds, or an ``httpx.Timeout`` whose four values are all finite.
        retry: The retry policy.
        tls: The TLS profile; the platform trust store when omitted.
        auth: Outbound credentials (see :mod:`agent_connector_sdk.auth`).
        headers: Default headers; credential-bearing names are rejected.
        limits: Connection pool limits.
        allow_plaintext: Permit ``http://`` to a non-loopback host.

    Raises:
        ValueError: on construction, when any of the rules above is broken.
    """

    base_url: str
    timeout: float | httpx.Timeout = DEFAULT_TIMEOUT_SECONDS
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    tls: ResolvedTLSProfile | None = None
    auth: httpx.Auth | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    limits: httpx.Limits | None = None
    allow_plaintext: bool = False

    def __post_init__(self) -> None:
        credential_headers = any(is_sensitive_name(name) for name in self.headers)
        problems = (
            _base_url_problem(self.base_url),
            _timeout_problem(self.timeout),
            "credential headers are not allowed; use auth"
            if credential_headers
            else None,
            _plaintext_problem(self.base_url, self.allow_plaintext),
        )
        problem = next((item for item in problems if item), None)
        if problem is not None:
            raise ValueError(problem)
