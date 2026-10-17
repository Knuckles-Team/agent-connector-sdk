"""How a governed client reaches one API, validated when it is built."""

from __future__ import annotations

import ipaddress
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from agent_connector_sdk.http.egress import normalize_private_hosts
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
        pin_egress: Resolve every request once, refuse destinations outside the
            public boundary, dial only the resolved address (``Host``/SNI kept)
            and require the connected peer to match it. Off by default, as in
            agent-utilities; it forbids proxies and redirects.
        allowed_private_hosts: Exact hostnames or IP literals that may resolve
            into private space (RFC 1918, RFC 6598, ULA, loopback); needs
            ``pin_egress``.
        allow_loopback: Permit loopback destinations under ``pin_egress``.
        verify_pinned_peer: Check the connected peer against the pin; disable
            only for an injected in-process test transport.

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
    pin_egress: bool = False
    allowed_private_hosts: tuple[str, ...] = ()
    allow_loopback: bool = False
    verify_pinned_peer: bool = True

    def __post_init__(self) -> None:
        credential_headers = any(is_sensitive_name(name) for name in self.headers)
        problems = (
            _base_url_problem(self.base_url),
            _timeout_problem(self.timeout),
            "credential headers are not allowed; use auth"
            if credential_headers
            else None,
            _plaintext_problem(self.base_url, self.allow_plaintext),
            self._egress_problem(),
        )
        problem = next((item for item in problems if item), None)
        if problem is not None:
            raise ValueError(problem)

    def _egress_problem(self) -> str | None:
        try:
            normalize_private_hosts(self.allowed_private_hosts)
        except ValueError as exc:
            return str(exc)
        if (self.allowed_private_hosts or self.allow_loopback) and not self.pin_egress:
            return "allowed_private_hosts and allow_loopback require pin_egress"
        if self.pin_egress and self.tls is not None and self.tls.proxy_url is not None:
            return "pin_egress does not accept a proxy"
        return None
