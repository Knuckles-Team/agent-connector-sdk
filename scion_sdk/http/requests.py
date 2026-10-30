"""A governed Requests session for SDKs that require Requests.

Install ``scion-sdk[requests]`` to use this adapter. New HTTP clients should
use the SDK's httpx factories.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import httpx
import requests

from scion_sdk.http.client import _check_airgap
from scion_sdk.http.options import DEFAULT_TIMEOUT_SECONDS
from scion_sdk.http.redaction import is_sensitive_name
from scion_sdk.tls.profile import ResolvedTLSProfile

__all__ = ["create_requests_session"]


class _RequestsSession(requests.Session):
    """Enforce the safety boundary even when a caller invokes send directly."""

    def send(
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        if not self.verify or not kwargs.get("verify", self.verify):
            raise ValueError("TLS verification cannot be disabled")
        timeout = kwargs.get("timeout")
        if timeout is None:
            timeout = DEFAULT_TIMEOUT_SECONDS
        values = timeout if isinstance(timeout, tuple) else (timeout,)
        if (isinstance(timeout, tuple) and len(timeout) != 2) or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
            for value in values
        ):
            raise ValueError("timeout must be finite and positive")
        kwargs["timeout"] = timeout
        proxies = kwargs.get("proxies") or self.proxies
        _check_airgap(
            httpx.Request(request.method or "GET", request.url or ""),
            "proxy" if proxies or self.trust_env else None,
        )
        return super().send(request, **kwargs)


def create_requests_session(
    *,
    tls: ResolvedTLSProfile | None = None,
    headers: Mapping[str, str] | None = None,
) -> requests.Session:
    """Build a Requests session with verified TLS, timeout and air-gap checks.

    The session does not read ambient proxy configuration by default. A TLS
    profile can configure trust, client keys and an explicit proxy. In air-gap
    mode the session refuses any proxy before it sends.
    """
    from scion_sdk.http.client import standard_headers

    if headers and any(is_sensitive_name(name) for name in headers):
        raise ValueError("credential headers are not allowed; use authentication")
    session = _RequestsSession()
    session.trust_env = False
    session.headers.update(standard_headers())
    if headers:
        session.headers.update(headers)
    if tls:
        tls.configure_requests_session(session)
    if not session.verify:
        session.close()
        raise ValueError("TLS verification cannot be disabled")
    return session
