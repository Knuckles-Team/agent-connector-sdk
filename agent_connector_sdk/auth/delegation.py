"""RFC 8693 token exchange on behalf of the MCP caller.

The subject token is the caller's access token as verified by the connector's
MCP server authentication (:mod:`agent_connector_sdk.mcp.auth`); an unverified
or absent token is never exchanged. Settings:

========================== ==================================================
``ENABLE_DELEGATION``      ``true`` to exchange tokens
``OIDC_TOKEN_URL``         the token endpoint
``OIDC_CLIENT_ID``         this connector's client identifier
``OIDC_CLIENT_SECRET_REF`` a secret reference to its client secret
``AUDIENCE``               the downstream audience
``DELEGATED_SCOPES``       requested scopes (default ``api``)
========================== ==================================================
"""

from __future__ import annotations

import functools
import hashlib
import threading
from collections import OrderedDict
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass

import anyio
import httpx
from fastmcp.server.dependencies import get_access_token

from agent_connector_sdk.auth.tokens import (
    AccessToken,
    TokenRequestError,
    request_access_token,
)
from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.references import (
    SecretReferenceError,
    parse_secret_reference,
)
from agent_connector_sdk.credentials.resolution import resolve_secret_reference
from agent_connector_sdk.credentials.resolver import (
    CredentialResolver,
    CredentialUnavailableError,
)
from agent_connector_sdk.exceptions import LoginRequiredError

__all__ = [
    "DelegatedTokenAuth",
    "DelegationSettings",
    "current_user_identity",
    "current_user_token",
    "exchange_token",
]

_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
_ACCESS_TYPE_URN = "urn:ietf:params:oauth:token-type:access_token"
_CACHE_SIZE = 256
_SKEW_SECONDS = 30.0


@dataclass(frozen=True)
class DelegationSettings:
    """Token exchange configuration; credentials only by reference."""

    enabled: bool = False
    token_endpoint: str = ""
    client_id: str = ""
    client_secret_ref: str = ""
    audience: str = ""
    scopes: str = "api"

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        missing = [
            name
            for name, value in (
                ("OIDC_TOKEN_URL", self.token_endpoint),
                ("OIDC_CLIENT_ID", self.client_id),
                ("OIDC_CLIENT_SECRET_REF", self.client_secret_ref),
                ("AUDIENCE", self.audience),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"delegation is enabled but {', '.join(missing)} is not set"
            )
        parse_secret_reference(self.client_secret_ref)

    @classmethod
    def from_settings(cls) -> DelegationSettings:
        """Read the settings in the module docstring."""
        return cls(
            enabled=bool(setting("ENABLE_DELEGATION", False)),
            token_endpoint=str(setting("OIDC_TOKEN_URL", "")),
            client_id=str(setting("OIDC_CLIENT_ID", "")),
            client_secret_ref=str(setting("OIDC_CLIENT_SECRET_REF", "")),
            audience=str(setting("AUDIENCE", "")),
            scopes=str(setting("DELEGATED_SCOPES", "api")),
        )


def current_user_token() -> str | None:
    """The verified access token of the MCP request being served, if any."""
    token = get_access_token()
    return token.token if token is not None else None


def current_user_identity() -> str | None:
    """An opaque, non-reversible reference to the caller for audit records."""
    token = get_access_token()
    subject = (
        (token.claims.get("sub") or token.client_id) if token is not None else None
    )
    if not subject:
        return None
    return (
        "delegated-actor:"
        + hashlib.sha256(str(subject).encode("utf-8")).hexdigest()[:32]
    )


def exchange_token(
    settings: DelegationSettings,
    *,
    subject_token: str,
    http_client: httpx.Client,
    resolver: CredentialResolver | None = None,
) -> AccessToken:
    """Exchange ``subject_token`` for a token for ``settings.audience``.

    Raises:
        TokenRequestError: delegation is disabled, the client secret is
            unavailable, or the exchange failed.
    """
    if not settings.enabled:
        raise TokenRequestError("delegation is not enabled")
    try:
        secret = resolve_secret_reference(settings.client_secret_ref, resolver)
    except (SecretReferenceError, CredentialUnavailableError) as exc:
        raise TokenRequestError("delegation client secret is unavailable") from exc
    form = {
        "grant_type": _EXCHANGE_GRANT,
        "subject_token": subject_token,
        "subject_token_type": _ACCESS_TYPE_URN,
        "requested_token_type": _ACCESS_TYPE_URN,
        "audience": settings.audience,
        "scope": settings.scopes,
    }
    return request_access_token(
        http_client,
        settings.token_endpoint,
        form=form,
        client_auth=(settings.client_id, secret),
    )


class DelegatedTokenAuth(httpx.Auth):
    """Authenticates each request with a token exchanged for the current caller.

    Exchanged tokens are cached per caller until shortly before they expire.

    Raises:
        LoginRequiredError: no verified caller token is available.
        TokenRequestError: the exchange failed.
    """

    def __init__(
        self,
        settings: DelegationSettings,
        *,
        http_client: httpx.Client,
        resolver: CredentialResolver | None = None,
    ) -> None:
        self._settings = settings
        self._client = http_client
        self._resolver = resolver
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, AccessToken] = OrderedDict()

    def _token_for(self, subject: str | None) -> str:
        if not subject:
            raise LoginRequiredError("no verified caller token to delegate")
        key = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        with self._lock:
            cached = self._cache.get(key)
            if cached is None or not cached.fresh(_SKEW_SECONDS):
                cached = exchange_token(
                    self._settings,
                    subject_token=subject,
                    http_client=self._client,
                    resolver=self._resolver,
                )
                self._cache[key] = cached
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_SIZE:
                self._cache.popitem(last=False)
            return cached.value

    def sync_auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        """Authenticate a synchronous request."""
        request.headers["Authorization"] = (
            f"Bearer {self._token_for(current_user_token())}"
        )
        yield request

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Authenticate an asynchronous request; the exchange runs in a worker thread."""
        exchange = functools.partial(self._token_for, current_user_token())
        request.headers["Authorization"] = (
            f"Bearer {await anyio.to_thread.run_sync(exchange)}"
        )
        yield request
