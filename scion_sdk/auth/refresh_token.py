"""OAuth 2.0 refresh-token grant with token caching, rotation and refresh."""

from __future__ import annotations

import threading

import httpx

from scion_sdk.auth.tokens import (
    AccessToken,
    TokenRequestError,
    request_access_token,
)
from scion_sdk.auth.values import header_safe
from scion_sdk.credentials.references import SecretReferenceError
from scion_sdk.credentials.resolution import resolve_secret_reference
from scion_sdk.credentials.resolver import (
    CredentialResolver,
    CredentialUnavailableError,
)

__all__ = ["RefreshTokenProvider"]

#: Refresh a cached token this many seconds before it expires.
REFRESH_SKEW_SECONDS = 30.0


class RefreshTokenProvider:
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
        self._token_url = token_url
        self._client_id = header_safe(client_id, what="client id")
        self._refresh_ref = refresh_token_ref
        self._secret_ref = client_secret_ref
        self._scope = scope
        self._client = http_client
        self._resolver = resolver
        self._lock = threading.Lock()
        self._token: AccessToken | None = None
        self._rotated: str | None = None

    def _secret(self, reference: str, what: str) -> str:
        try:
            return resolve_secret_reference(reference, self._resolver)
        except (SecretReferenceError, CredentialUnavailableError) as exc:
            raise TokenRequestError(f"{what} is unavailable") from exc

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
