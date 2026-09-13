"""OAuth 2.0 token endpoint requests and access tokens."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx

from agent_connector_sdk.exceptions import AuthError
from agent_connector_sdk.http.bodies import read_bounded
from agent_connector_sdk.http.errors import HttpProblemError
from agent_connector_sdk.http.responses import ensure_success

__all__ = [
    "AccessToken",
    "TokenRequestError",
    "parse_token_response",
    "request_access_token",
]

_MAX_TOKEN_RESPONSE_BYTES = 1024 * 1024
_DEFAULT_TTL_SECONDS = 300.0
_MAX_TTL_SECONDS = 86_400.0


class TokenRequestError(AuthError):
    """A token could not be obtained; the message never contains credentials."""


@dataclass(frozen=True)
class AccessToken:
    """An access token and when it expires on the monotonic clock."""

    value: str = field(repr=False)
    ttl_seconds: float
    expires_at: float

    def fresh(self, skew_seconds: float) -> bool:
        """Whether the token is still valid ``skew_seconds`` from now."""
        return time.monotonic() < self.expires_at - skew_seconds


def parse_token_response(body: bytes) -> AccessToken:
    """Validate a token endpoint's JSON response.

    Raises:
        TokenRequestError: the body is not an object with a bounded
            ``access_token`` and an ``expires_in`` between 1 second and 1 day.
    """
    try:
        payload = json.loads(body)
    except ValueError:
        raise TokenRequestError("token response is not valid JSON") from None
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not 1 <= len(token) <= 65_536:
        raise TokenRequestError("token response has no valid access_token")
    raw_ttl = payload.get("expires_in", _DEFAULT_TTL_SECONDS)
    ttl = (
        float(raw_ttl)
        if isinstance(raw_ttl, int | float) and not isinstance(raw_ttl, bool)
        else -1.0
    )
    if not (math.isfinite(ttl) and 1.0 <= ttl <= _MAX_TTL_SECONDS):
        raise TokenRequestError("token response has an invalid expires_in")
    return AccessToken(token, ttl, time.monotonic() + ttl)


def request_access_token(
    client: httpx.Client,
    url: str,
    *,
    form: Mapping[str, str],
    client_auth: tuple[str, str] | None = None,
) -> AccessToken:
    """POST a form to a token endpoint and parse the token.

    Raises:
        TokenRequestError: the request failed, was rejected or returned an
            invalid token; the underlying error is the ``__cause__``.
    """
    try:
        with client.stream("POST", url, data=dict(form), auth=client_auth) as response:
            ensure_success(response)
            body = read_bounded(response, _MAX_TOKEN_RESPONSE_BYTES)
    except (HttpProblemError, httpx.HTTPError) as exc:
        raise TokenRequestError("token request failed") from exc
    return parse_token_response(body)
