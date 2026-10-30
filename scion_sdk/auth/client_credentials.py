"""OAuth 2.0 client-credentials grant with token caching and refresh."""

from __future__ import annotations

import functools
from collections.abc import AsyncGenerator, Generator
from typing import Any

import anyio
import httpx
import httpx2

from scion_sdk.auth._cached_provider import (
    REFRESH_SKEW_SECONDS,
    CachedTokenProvider,
    resolve_or_unavailable,
)
from scion_sdk.auth.tokens import AccessToken, request_access_token
from scion_sdk.auth.values import header_safe
from scion_sdk.credentials.resolver import CredentialResolver

__all__ = [
    "REFRESH_SKEW_SECONDS",
    "ClientCredentialsAuth",
    "ClientCredentialsTokenProvider",
]


class ClientCredentialsTokenProvider(CachedTokenProvider):
    """A thread-safe, self-refreshing client-credentials token cache.

    The client secret is resolved from ``client_secret_ref`` at every mint, so a
    rotated secret is picked up by the next refresh.

    Args:
        token_url: The token endpoint.
        client_id: The OAuth client identifier.
        client_secret_ref: A secret reference to the client secret. Exactly
            one of ``client_secret_ref`` and ``client_secret`` must be set.
        client_secret: A literal client secret, for a connector migrating
            from a prior client-credentials helper that already calls this
            constructor with a secret value in hand. It is held only in
            memory and never logged, repr'd, or serialized.
        http_client: The governed client used for the token endpoint.
        audience: Optional ``audience`` parameter.
        scope: Optional space-separated scopes.
        resolver: Resolves the secret reference; unused when ``client_secret``
            is given.

    Raises:
        ValueError: both or neither of ``client_secret_ref`` and
            ``client_secret`` are set.
    """

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret_ref: str = "",
        client_secret: str | None = None,
        http_client: httpx.Client,
        audience: str = "",
        scope: str = "",
        resolver: CredentialResolver | None = None,
    ) -> None:
        super().__init__(self._mint)
        if bool(client_secret_ref) == (client_secret is not None):
            raise ValueError(
                "exactly one of client_secret_ref and client_secret must be set"
            )
        self._token_url = token_url
        self._client_id = header_safe(client_id, what="client id")
        self._secret_ref = client_secret_ref
        self._literal_secret = client_secret
        self._client = http_client
        self._form = {"grant_type": "client_credentials"}
        self._form.update(
            {k: v for k, v in (("audience", audience), ("scope", scope)) if v}
        )
        self._resolver = resolver

    @property
    def access_token_ttl(self) -> float | None:
        """The last minted token's lifetime in seconds, ``None`` before the first mint."""
        return self._token.ttl_seconds if self._token else None

    def _client_secret(self) -> str:
        if self._literal_secret is not None:
            return self._literal_secret
        return resolve_or_unavailable(self._secret_ref, self._resolver, "client secret")

    def _mint(self) -> AccessToken:
        secret = self._client_secret()
        return request_access_token(
            self._client,
            self._token_url,
            form=self._form,
            client_auth=(self._client_id, secret),
        )


class ClientCredentialsAuth(httpx.Auth, httpx2.Auth):
    """Attaches the provider's token; a 401 re-mints once and retries once.

    It is both an ``httpx.Auth`` (API clients) and an ``httpx2.Auth`` (the MCP
    client transport FastMCP uses), so API calls and MCP endpoints share one
    token cache and one refresh path. A failed mint raises
    :class:`TokenRequestError`; the request is never sent without credentials.
    """

    def __init__(self, provider: ClientCredentialsTokenProvider) -> None:
        self._provider = provider

    @property
    def provider(self) -> ClientCredentialsTokenProvider:
        """The token cache this auth draws from."""
        return self._provider

    def auth_flow(self, request: Any) -> Generator[Any, Any, None]:
        """The synchronous flow (both client libraries call it)."""
        return self.sync_auth_flow(request)

    def sync_auth_flow(self, request: Any) -> Generator[Any, Any, None]:
        """Authenticate a synchronous request."""
        request.headers["Authorization"] = f"Bearer {self._provider.get_token()}"
        response = yield request
        if response.status_code == 401:
            fresh = self._provider.get_token(force=True)
            request.headers["Authorization"] = f"Bearer {fresh}"
            yield request

    async def async_auth_flow(self, request: Any) -> AsyncGenerator[Any, Any]:
        """Authenticate an asynchronous request; minting runs in a worker thread."""
        token = await anyio.to_thread.run_sync(self._provider.get_token)
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            refresh = functools.partial(self._provider.get_token, force=True)
            fresh = await anyio.to_thread.run_sync(refresh)
            request.headers["Authorization"] = f"Bearer {fresh}"
            yield request
