"""Static bearer, HTTP Basic and API-key credentials resolved from references."""

from __future__ import annotations

from collections.abc import Generator

import httpx

from agent_connector_sdk.auth.values import header_safe, resolved_credential
from agent_connector_sdk.credentials.resolver import CredentialResolver

__all__ = ["ApiKeyAuth", "BearerAuth", "api_key_auth", "basic_auth", "bearer_auth"]


class BearerAuth(httpx.Auth):
    """Sends ``Authorization: Bearer <token>``."""

    def __init__(self, token: str) -> None:
        self._token = header_safe(token, what="bearer token")

    def __repr__(self) -> str:
        return "BearerAuth(token=<redacted>)"

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        """Attach the bearer token."""
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


class ApiKeyAuth(httpx.Auth):
    """Sends an API key in a header (optionally prefixed) or a query parameter."""

    def __init__(
        self, key: str, *, header: str = "", query: str = "", prefix: str = ""
    ) -> None:
        if bool(header) == bool(query):
            raise ValueError("API key auth needs exactly one of header or query")
        self._key = header_safe(key, what="API key")
        self._header = header
        self._query = query
        self._prefix = prefix

    def __repr__(self) -> str:
        return f"ApiKeyAuth(header={self._header!r}, query={self._query!r}, key=<redacted>)"

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        """Attach the key."""
        if self._header:
            request.headers[self._header] = f"{self._prefix}{self._key}"
        else:
            request.url = request.url.copy_merge_params({self._query: self._key})
        yield request


def bearer_auth(
    token_ref: str, *, resolver: CredentialResolver | None = None
) -> BearerAuth:
    """Bearer auth whose token is the value of ``token_ref``."""
    return BearerAuth(resolved_credential(token_ref, resolver))


def basic_auth(
    username: str, password_ref: str, *, resolver: CredentialResolver | None = None
) -> httpx.BasicAuth:
    """HTTP Basic auth whose password is the value of ``password_ref``."""
    if ":" in header_safe(username, what="username"):
        raise ValueError("username must not contain ':'")
    return httpx.BasicAuth(username, resolved_credential(password_ref, resolver))


def api_key_auth(
    key_ref: str,
    *,
    header: str = "",
    query: str = "",
    prefix: str = "",
    resolver: CredentialResolver | None = None,
) -> ApiKeyAuth:
    """API-key auth whose key is the value of ``key_ref``."""
    key = resolved_credential(key_ref, resolver)
    return ApiKeyAuth(key, header=header, query=query, prefix=prefix)
