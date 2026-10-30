"""OAuth 2.0 refresh-token grant with token caching, rotation and refresh."""

from __future__ import annotations

import httpx

from scion_sdk.auth._cached_provider import (
    CachedTokenProvider,
    resolve_or_unavailable,
)
from scion_sdk.auth.tokens import AccessToken, request_access_token
from scion_sdk.auth.values import header_safe
from scion_sdk.credentials.resolver import CredentialResolver

__all__ = ["RefreshTokenProvider"]


class RefreshTokenProvider(CachedTokenProvider):
    """A thread-safe, self-refreshing refresh-token grant token cache.

    It has the same ``get_token(force=...)`` surface as
    :class:`~scion_sdk.auth.client_credentials.ClientCredentialsTokenProvider`,
    so :class:`~scion_sdk.auth.client_credentials.ClientCredentialsAuth`
    attaches it and re-mints once on a 401. The refresh token and client secret
    are resolved from references at the first mint and the client secret at every
    mint; when the server rotates the refresh token the new one is kept in
    memory only and never logged.
    """

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        refresh_token_ref: str,
        client_secret_ref: str = "",
        http_client: httpx.Client,
        scope: str = "",
        resolver: CredentialResolver | None = None,
    ) -> None:
        super().__init__(self._mint)
        self._token_url = token_url
        self._client_id = header_safe(client_id, what="client id")
        self._refresh_ref = refresh_token_ref
        self._secret_ref = client_secret_ref
        self._scope = scope
        self._client = http_client
        self._resolver = resolver
        self._rotated: str | None = None

    def _secret(self, reference: str, what: str) -> str:
        return resolve_or_unavailable(reference, self._resolver, what)

    def _mint(self) -> AccessToken:
        refresh = self._rotated or self._secret(self._refresh_ref, "refresh token")
        form = {"grant_type": "refresh_token", "refresh_token": refresh}
        if self._scope:
            form["scope"] = self._scope
        client_auth: tuple[str, str] | None = None
        if self._secret_ref:
            client_auth = (
                self._client_id,
                self._secret(self._secret_ref, "client secret"),
            )
        else:
            form["client_id"] = self._client_id
        token = request_access_token(
            self._client, self._token_url, form=form, client_auth=client_auth
        )
        if token.refresh_token:
            self._rotated = token.refresh_token
        return token
