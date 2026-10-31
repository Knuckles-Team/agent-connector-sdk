"""Response decoding and verb helpers mixed into :class:`BaseApiClient`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from scion_sdk.http.support_rate import RateLimitSnapshot, _redact


class _ResponseDecoding:
    """Error mapping and body parsing; the host supplies the mapping attributes."""

    error_map: dict[int, type[Exception]]
    default_error: type[Exception]
    max_retries_429: int
    _auth: Any
    _last_rate_limit: RateLimitSnapshot | None

    @property
    def rate_limit(self) -> RateLimitSnapshot | None:
        """The most recent rate-limit snapshot observed on any response."""
        return self._last_rate_limit

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


class _VerbMethods:
    """The HTTP verb shortcuts over :meth:`request`."""

    request: Callable[..., dict[str, Any]]

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
