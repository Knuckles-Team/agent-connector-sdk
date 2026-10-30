"""Browser OAuth (PKCE) login and token lifecycle (SCION-CONNECTOR-CONTROL-R014.11).

Replaces ``agent_utilities.security.browser_auth`` for connectors that let an
operator sign in interactively (leanix). :func:`generate_pkce` makes an S256
verifier and challenge; :class:`BaseBrowserAuthManager` runs the loopback
authorization-code flow, exchanges and refreshes tokens, and keeps them in a
:class:`TokenStore`. The default :class:`FileTokenStore` writes one owner-only
(0600) JSON file per key under the connector config directory. Any object with
``get(key)`` and ``set(key, value)`` may be passed as ``secrets_client``.
The callback handler never logs the request line, which carries the code.
"""

from __future__ import annotations

import json
import logging
import secrets
import sys
import time
from collections.abc import Callable
from typing import Any

from scion_sdk.auth.browser_discovery import _OidcDiscovery
from scion_sdk.auth.browser_flow import _AuthorizationCodeFlow
from scion_sdk.auth.browser_loopback import (
    BaseLoopbackCallbackHandler,
    BaseLoopbackCallbackServer,
)
from scion_sdk.auth.browser_store import FileTokenStore, TokenStore
from scion_sdk.auth.browser_support import generate_pkce
from scion_sdk.config import setting

__all__ = [
    "BaseBrowserAuthManager",
    "BaseLoopbackCallbackHandler",
    "BaseLoopbackCallbackServer",
    "FileTokenStore",
    "TokenStore",
    "generate_pkce",
]

logger = logging.getLogger(__name__)


class BaseBrowserAuthManager(_AuthorizationCodeFlow, _OidcDiscovery):
    """Generic base class managing browser-based OAuth PKCE authorization, storage, and refresh lifecycle."""

    def __init__(
        self,
        client_id: str,
        auth_endpoint: str,
        token_endpoint: str,
        scopes: str,
        secret_key: str,
        redirect_host: str = "127.0.0.1",
        redirect_port: int = 56122,
        redirect_path: str = "/callback",
        secrets_client: TokenStore | None = None,
        refresh_skew_seconds: int = 120,
        oidc_discovery_url: str | None = None,
        validate_endpoint_fn: Callable[[str, str], str] | None = None,
        extra_auth_params: dict[str, str] | None = None,
        extra_token_params: dict[str, str] | None = None,
        api_key_secret_key: str | None = None,
        api_key_env_var: str | None = None,
    ):
        self.client_id = client_id
        self.auth_endpoint = auth_endpoint
        self.token_endpoint = token_endpoint
        self.scopes = scopes
        self.secret_key = secret_key
        self.redirect_host = redirect_host
        self.redirect_port = redirect_port
        self.redirect_path = redirect_path
        self.secrets_client: TokenStore = secrets_client or FileTokenStore()
        self.refresh_skew_seconds = refresh_skew_seconds
        self.oidc_discovery_url = oidc_discovery_url
        self.validate_endpoint_fn = validate_endpoint_fn
        self.extra_auth_params = extra_auth_params or {}
        self.extra_token_params = extra_token_params or {}
        self.api_key_secret_key = api_key_secret_key
        self.api_key_env_var = api_key_env_var

    def get_cached_tokens(self) -> dict[str, Any] | None:
        """Retrieve the stored token set."""
        raw = self.secrets_client.get(self.secret_key)
        if not raw:
            return None
        try:
            tokens: dict[str, Any] = json.loads(raw)
            return tokens
        except Exception as exc:
            logger.warning(
                "Failed to parse cached OAuth tokens for %r: %s", self.secret_key, exc
            )
            return None

    def save_tokens(self, tokens: dict[str, Any]) -> None:
        """Persist the token set."""
        self.secrets_client.set(self.secret_key, json.dumps(tokens))

    def refresh_tokens(self, tokens: dict[str, Any]) -> dict[str, Any]:
        """Refresh an expiring or expired access token using refresh_token."""
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh_token found in credentials.")

        _, token_endpoint = self._discover_endpoints()
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }
        if self.extra_token_params:
            data.update(self.extra_token_params)

        import httpx

        try:
            response = httpx.post(
                token_endpoint,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=data,
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.error(
                "OAuth token refresh failed for endpoint %r: %s", token_endpoint, exc
            )
            raise ValueError(f"Failed to refresh tokens: {exc}") from exc

        new_tokens = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token", refresh_token),
            "expires_at": time.time() + float(payload.get("expires_in", 3600)),
        }
        self.save_tokens(new_tokens)
        return new_tokens

    def _resolve_api_key(self) -> str | None:
        """Return a configured direct API key, if this manager supports one."""
        if not (self.api_key_secret_key or self.api_key_env_var):
            return None
        stored = (
            self.secrets_client.get(self.api_key_secret_key)
            if self.api_key_secret_key
            else None
        )
        if stored:
            return stored
        return setting(self.api_key_env_var) if self.api_key_env_var else None

    def _load_or_login_tokens(self, auto_login: bool) -> dict[str, Any] | None:
        """Load cached OAuth tokens, optionally recovering through interactive login."""
        tokens = self.get_cached_tokens()
        if tokens or not auto_login:
            return tokens

        logger.info(
            "Cached tokens missing for %r. Triggering interactive login...",
            self.secret_key,
        )
        try:
            return self.login()
        except Exception as exc:
            logger.error("Interactive login flow auto-trigger failed: %s", exc)
            return None

    def _refresh_if_expiring(self, tokens: dict[str, Any]) -> dict[str, Any] | None:
        """Refresh tokens inside the configured skew window, failing closed."""
        expires_at = tokens.get("expires_at", 0.0)
        if time.time() + self.refresh_skew_seconds < expires_at:
            return tokens
        try:
            return self.refresh_tokens(tokens)
        except Exception as exc:
            logger.error("Proactive token refresh failed: %s", exc)
            return None

    def resolve_credentials(self, auto_login: bool = False) -> str | None:
        """Master credential resolver.

        Checks direct API Key overrides first. Otherwise resolves, validates, and
        proactively refreshes stored OAuth tokens.
        """
        api_key = self._resolve_api_key()
        if api_key:
            return api_key

        tokens = self._load_or_login_tokens(auto_login)
        if not tokens:
            return None
        tokens = self._refresh_if_expiring(tokens)
        if not tokens:
            return None
        return tokens.get("access_token")

    def login(self) -> dict[str, Any]:
        """Execute the interactive OAuth PKCE flow."""
        auth_endpoint, token_endpoint = self._discover_endpoints()
        verifier, challenge = generate_pkce()
        state = secrets.token_urlsafe(32)
        server = self._start_loopback_server(state)
        auth_url = self._build_authorization_url(auth_endpoint, challenge, state)
        self._announce_authorization(auth_url)
        auth_code = self._get_authorization_code(server, state)
        if not auth_code:
            raise ValueError("Authentication cancelled or code was not provided.")

        tokens = self._exchange_authorization_code(
            token_endpoint, auth_code, verifier, challenge
        )
        self.save_tokens(tokens)
        print("Successfully authenticated and stored credentials!\n", file=sys.stderr)
        return tokens
