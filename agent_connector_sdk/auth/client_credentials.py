"""OAuth 2.0 client-credentials grant with token caching and refresh."""

from __future__ import annotations

import functools
import threading
from collections.abc import AsyncGenerator, Generator
from typing import Any

import anyio
import httpx
import httpx2

from agent_connector_sdk.auth.tokens import (
    AccessToken,
    TokenRequestError,
    request_access_token,
)
from agent_connector_sdk.auth.values import header_safe
from agent_connector_sdk.credentials.references import SecretReferenceError
from agent_connector_sdk.credentials.resolution import resolve_secret_reference
from agent_connector_sdk.credentials.resolver import (
    CredentialResolver,
    CredentialUnavailableError,
)

__all__ = ["ClientCredentialsAuth", "ClientCredentialsTokenProvider"]

#: Refresh a cached token this many seconds before it expires.
REFRESH_SKEW_SECONDS = 30.0


class ClientCredentialsTokenProvider:
    """A thread-safe, self-refreshing client-credentials token cache.

    The client secret is resolved from ``client_secret_ref`` at every mint, so a
    rotated secret is picked up by the next refresh.

    Args:
        token_url: The token endpoint.
        client_id: The OAuth client identifier.
        client_secret_ref: A secret reference to the client secret.
        http_client: The governed client used for the token endpoint.
        audience: Optional ``audience`` parameter.
        scope: Optional space-separated scopes.
        resolver: Resolves the secret reference.
    """

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret_ref: str,
        http_client: httpx.Client,
        audience: str = "",
        scope: str = "",
        resolver: CredentialResolver | None = None,
    ) -> None:
        self._token_url = token_url
        self._client_id = header_safe(client_id, what="client id")
        self._secret_ref = client_secret_ref
        self._client = http_client
        self._form = {"grant_type": "client_credentials"}
        self._form.update(
            {k: v for k, v in (("audience", audience), ("scope", scope)) if v}
        )
        self._resolver = resolver
        self._lock = threading.Lock()
        self._token: AccessToken | None = None

    @property
    def access_token_ttl(self) -> float | None:
        """The last minted token's lifetime in seconds, ``None`` before the first mint."""
        return self._token.ttl_seconds if self._token else None

    def _mint(self) -> AccessToken:
        try:
            secret = resolve_secret_reference(self._secret_ref, self._resolver)
        except (SecretReferenceError, CredentialUnavailableError) as exc:
            raise TokenRequestError("client secret is unavailable") from exc
        return request_access_token(
            self._client,
            self._token_url,
            form=self._form,
            client_auth=(self._client_id, secret),
        )

    def get_token(self, *, force: bool = False) -> str:
        """A cached token, minted when missing, near expiry or ``force``d.

        Raises:
            TokenRequestError: minting failed.
        """
        with self._lock:
            if (
                force
                or self._token is None
                or not self._token.fresh(REFRESH_SKEW_SECONDS)
            ):
                self._token = self._mint()
            return self._token.value


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
