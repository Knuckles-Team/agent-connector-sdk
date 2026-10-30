"""Class-based API client base and auth strategies (SCION-CONNECTOR-CONTROL-R014.10).

Replaces ``agent_utilities.httpsupport`` for connectors that subclass a shared
client instead of calling :func:`scion_sdk.http.create_http_client`:

* :class:`AuthHeaderInjector` (anonymous base), :class:`TokenAuth`,
  :class:`BasicAuth` and :class:`QueryApiKeyAuth` contribute headers or query
  parameters on every request. A strategy may define ``invalidate()`` to opt in
  to one transparent retry after HTTP 401.
* :class:`BaseApiClient` joins relative endpoints under ``base_url``, returns
  the envelope ``{"status_code", "data", "rate_limit"}``, captures rate-limit
  headers, backs off a bounded number of times on HTTP 429, maps error
  statuses to the SDK exception types, and redacts the strategy's secrets from
  every raised message. TLS comes from the SDK runtime TLS profile for
  ``tls_service``; ``verify``/``cert``/``proxy``/``trust_env`` overrides are
  refused.
"""

from __future__ import annotations

import time
from base64 import b64encode
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from scion_sdk.exceptions import (
    ApiError,
    AuthError,
    ParameterError,
    UnauthorizedError,
)
from scion_sdk.http.retry import parse_retry_after

__all__ = [
    "DEFAULT_ERROR_MAP",
    "DEFAULT_MAX_RETRIES_429",
    "AuthHeaderInjector",
    "BaseApiClient",
    "BasicAuth",
    "DestructiveOperationError",
    "QueryApiKeyAuth",
    "RateLimitSnapshot",
    "TokenAuth",
]

JSON_CONTENT_TYPE = "application/json"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_RETRIES_429 = 3
DEFAULT_RETRY_AFTER_CAP_S = 60.0
REDACTED = "[REDACTED]"

#: Default status -> exception mapping.
DEFAULT_ERROR_MAP: dict[int, type[Exception]] = {
    400: ParameterError,
    401: AuthError,
    403: UnauthorizedError,
    404: ParameterError,
}


class AuthHeaderInjector:
    """Base auth strategy: injects nothing (anonymous access)."""

    def headers(self) -> dict[str, str]:
        """Headers merged into every request."""
        return {}

    def params(self) -> dict[str, str]:
        """Query parameters merged into every request."""
        return {}

    def secrets(self) -> list[str]:
        """Literal secret values redacted from raised messages."""
        return []


class TokenAuth(AuthHeaderInjector):
    """A header token with a configurable header name and scheme prefix.

    Exactly one of ``token`` or ``token_provider`` is required. A provider is
    called on every request, so a delegated token manager keeps control of
    caching and refresh. ``prefix=None`` sends the bare token (``X-API-Key``).
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        token_provider: Callable[[], str] | None = None,
        header: str = "Authorization",
        prefix: str | None = "Bearer",
    ) -> None:
        if (token is None) == (token_provider is None):
            raise ValueError(
                "TokenAuth requires exactly one of 'token' or 'token_provider'"
            )
        self._token = token
        self._token_provider = token_provider
        self.header = header
        self.prefix = prefix or ""

    def _current_token(self) -> str:
        if self._token_provider is not None:
            return self._token_provider()
        return self._token or ""

    def headers(self) -> dict[str, str]:
        token = self._current_token()
        return {self.header: f"{self.prefix} {token}" if self.prefix else token}

    def secrets(self) -> list[str]:
        return [self._token] if self._token else []


class BasicAuth(AuthHeaderInjector):
    """RFC 7617 ``Authorization: Basic`` credentials."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self._password = password

    def headers(self) -> dict[str, str]:
        raw = f"{self.username}:{self._password}".encode()
        return {"Authorization": f"Basic {b64encode(raw).decode('ascii')}"}

    def secrets(self) -> list[str]:
        return [self._password] if self._password else []


class QueryApiKeyAuth(AuthHeaderInjector):
    """An API key carried as a query parameter."""

    def __init__(self, param: str, key: str) -> None:
        if not param or not key:
            raise ValueError("QueryApiKeyAuth requires both 'param' and 'key'")
        self.param = param
        self._key = key

    def params(self) -> dict[str, str]:
        return {self.param: self._key}

    def secrets(self) -> list[str]:
        return [self._key]


class DestructiveOperationError(PermissionError):
    """A destructive operation was attempted while gated off."""


@dataclass(frozen=True)
class RateLimitSnapshot:
    """The rate-limit headers observed on one response."""

    limit: int | None
    remaining: int | None
    reset: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _header_number(headers: Mapping[str, str], *names: str) -> float | None:
    for name in names:
        value = headers.get(name)
        if value is None:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None


def _rate_limit(headers: Mapping[str, str]) -> RateLimitSnapshot | None:
    limit = _header_number(headers, "X-RateLimit-Limit", "X-Rate-Limit-Limit")
    remaining = _header_number(
        headers, "X-RateLimit-Remaining", "X-Rate-Limit-Remaining"
    )
    reset = _header_number(headers, "X-RateLimit-Reset", "X-Rate-Limit-Reset")
    if limit is None and remaining is None and reset is None:
        return None
    return RateLimitSnapshot(
        limit=int(limit) if limit is not None else None,
        remaining=int(remaining) if remaining is not None else None,
        reset=reset,
    )


def _backoff_seconds(headers: Mapping[str, str], cap: float) -> float:
    delay = parse_retry_after(headers.get("Retry-After"))
    if delay is None:
        reset = _header_number(headers, "X-Rate-Limit-Reset", "X-RateLimit-Reset")
        if reset is not None:
            delay = max(0.0, reset - time.time()) if reset > 1e9 else reset
    return min(max(delay if delay is not None else 1.0, 0.0), cap)


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


class BaseApiClient:
    """Synchronous connector API client base (see the module docstring).

    Args:
        base_url: Root URL relative endpoints join under.
        auth: An :class:`AuthHeaderInjector` strategy; ``None`` is anonymous.
        headers: Extra default headers merged over :meth:`default_headers`.
        tls_service: Settings prefix of the runtime TLS profile.
        tls_profile: Optional named profile in the TLS catalog.
        tls_profile_ref: Optional secret reference holding a profile.
        timeout: Default request timeout in seconds.
        max_retries_429: Bounded automatic retries on HTTP 429.
        retry_after_cap_s: Ceiling on one 429 backoff sleep.
        error_map: Status -> exception overrides merged over the defaults.
        default_error: Exception class for unmapped error statuses.
        allow_destructive: Enables operations guarded by :meth:`guard_destructive`.
        include_response_headers: Adds ``"headers"`` to every envelope.
        transport: An httpx transport override (tests use ``httpx.MockTransport``).
    """

    def __init__(
        self,
        base_url: str,
        *,
        auth: AuthHeaderInjector | None = None,
        headers: dict[str, str] | None = None,
        tls_service: str = "fleet-http",
        tls_profile: str | None = None,
        tls_profile_ref: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        max_retries_429: int = DEFAULT_MAX_RETRIES_429,
        retry_after_cap_s: float = DEFAULT_RETRY_AFTER_CAP_S,
        error_map: dict[int, type[Exception]] | None = None,
        default_error: type[Exception] = ApiError,
        allow_destructive: bool = False,
        include_response_headers: bool = False,
        transport: httpx.BaseTransport | None = None,
        **httpx_kwargs: Any,
    ) -> None:
        if {"verify", "cert", "proxy", "trust_env"}.intersection(httpx_kwargs):
            raise ValueError("transport security must use a TLS profile")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries_429 = max_retries_429
        self.retry_after_cap_s = retry_after_cap_s
        self.allow_destructive = allow_destructive
        self.include_response_headers = include_response_headers
        self.error_map = {**DEFAULT_ERROR_MAP, **(error_map or {})}
        self.default_error = default_error
        self._auth = auth or AuthHeaderInjector()
        self._extra_headers = dict(headers or {})
        self._last_rate_limit: RateLimitSnapshot | None = None
        if transport is not None:
            httpx_kwargs["transport"] = transport
        from scion_sdk.tls.resolve import resolve_tls_profile

        trust = resolve_tls_profile(
            tls_service, profile_name=tls_profile, profile_ref=tls_profile_ref
        )
        self._trust = trust
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            **trust.httpx_kwargs(),
            **httpx_kwargs,
        )

    @property
    def rate_limit(self) -> RateLimitSnapshot | None:
        """The most recent rate-limit snapshot observed on any response."""
        return self._last_rate_limit

    def default_headers(self) -> dict[str, str]:
        """Headers every request starts from; override per API."""
        return {"Accept": JSON_CONTENT_TYPE}

    def guard_destructive(self, operation: str) -> None:
        """Raise unless the client was built with ``allow_destructive=True``."""
        if not self.allow_destructive:
            raise DestructiveOperationError(
                f"Destructive operation {operation!r} is disabled. "
                "Construct the client with allow_destructive=True to enable it."
            )

    def _merged_headers(
        self,
        headers: dict[str, str] | None,
        content_type: str | None,
        accept: str | None,
    ) -> dict[str, str]:
        merged = {
            **self.default_headers(),
            **self._extra_headers,
            **self._auth.headers(),
            **(headers or {}),
        }
        if content_type:
            merged["Content-Type"] = content_type
        if accept:
            merged["Accept"] = accept
        return merged

    def _merged_params(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        merged = {
            **{k: v for k, v in (params or {}).items() if v is not None},
            **self._auth.params(),
        }
        return merged or None

    @staticmethod
    def _parse_body(response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        if "json" in response.headers.get("Content-Type", ""):
            try:
                return response.json()
            except ValueError:
                return response.text
        return response.text

    def _map_error(self, response: httpx.Response, data: Any) -> Exception:
        """Map an error response to an exception (override for bespoke APIs)."""
        detail = ""
        if isinstance(data, dict):
            detail = str(
                data.get("detail")
                or data.get("message")
                or data.get("error")
                or data.get("errorSummary")
                or ""
            )
        message = (
            f"HTTP {response.status_code} for "
            f"{response.request.method} {response.request.url.path}"
        )
        if detail:
            message = f"{message}: {detail}"
        if response.status_code == 429:
            limits = self.rate_limit
            message = (
                f"{message} - rate limited after {self.max_retries_429} retries "
                f"(remaining={limits.remaining if limits else None}, "
                f"reset={limits.reset if limits else None})"
            )
        message = _redact(message, self._auth.secrets())
        return self.error_map.get(response.status_code, self.default_error)(message)

    def _send(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        data: Any | None = None,
        content: bytes | str | None = None,
        headers: dict[str, str] | None = None,
        content_type: str | None = None,
        accept: str | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        merged_params = self._merged_params(params)
        attempts = 0
        refreshed = False
        while True:
            response = self._client.request(
                method,
                endpoint,
                params=merged_params,
                json=json,
                data=data,
                content=content,
                headers=self._merged_headers(headers, content_type, accept),
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
            snapshot = _rate_limit(response.headers)
            if snapshot is not None:
                self._last_rate_limit = snapshot
            if response.status_code == 429 and attempts < self.max_retries_429:
                attempts += 1
                delay = _backoff_seconds(response.headers, self.retry_after_cap_s)
                if delay > 0:
                    time.sleep(delay)
                continue
            invalidate = getattr(self._auth, "invalidate", None)
            if response.status_code == 401 and not refreshed and callable(invalidate):
                invalidate()
                refreshed = True
                continue
            return response

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        raise_for_status: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send one request and return the response envelope.

        Raises the mapped exception on HTTP >= 400 unless
        ``raise_for_status=False``.
        """
        response = self._send(method, endpoint, **kwargs)
        body = self._parse_body(response)
        if raise_for_status and response.status_code >= 400:
            raise self._map_error(response, body)
        last = self.rate_limit
        envelope: dict[str, Any] = {
            "status_code": response.status_code,
            "data": body,
            "rate_limit": last.to_dict() if last else None,
        }
        if self.include_response_headers:
            envelope["headers"] = dict(response.headers)
        return envelope

    def get(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("PUT", endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("PATCH", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("DELETE", endpoint, **kwargs)

    def head(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("HEAD", endpoint, **kwargs)

    def close(self) -> None:
        """Close the httpx client and release runtime TLS material."""
        self._client.close()
        self._trust.cleanup()

    def __enter__(self) -> BaseApiClient:
        return self

    def __exit__(self, *_exc_info: Any) -> None:
        self.close()
