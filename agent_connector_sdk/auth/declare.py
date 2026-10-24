"""One-line auth declarations and the client factory a connector calls.

A connector declares how it authenticates and the SDK builds the governed
client, the best implementation of each scheme from one configuration surface::

    get_client = client_factory(
        url_env="JELLYFIN_URL", auth=Bearer(env="JELLYFIN_TOKEN"), tls="jellyfin"
    )

Every declaration names a secret by environment variable (``env=``) or by
``env://`` / ``openbao://`` reference (``ref=``); no declaration holds a value.
Static credentials follow a rotated secret after a 401, OAuth tokens refresh
before expiry and re-mint once on a 401, the TLS profile (CA bundle, client
certificate, minimum version) resolves from ``<TLS>_*`` settings, and secrets
never reach a repr, log record or error message.
"""

from __future__ import annotations

import base64
import threading
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from agent_connector_sdk.auth.client_credentials import (
    ClientCredentialsAuth,
    ClientCredentialsTokenProvider,
)
from agent_connector_sdk.auth.delegation import DelegatedTokenAuth, DelegationSettings
from agent_connector_sdk.auth.oidc import discover_token_endpoint
from agent_connector_sdk.auth.refresh_token import RefreshTokenProvider
from agent_connector_sdk.auth.rotating import RotatingAuth, SessionLoginAuth
from agent_connector_sdk.auth.values import resolved_credential
from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.resolution import resolve_secret_reference
from agent_connector_sdk.credentials.resolver import CredentialResolver
from agent_connector_sdk.exceptions import AuthError
from agent_connector_sdk.http.client import create_http_client
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.retry import RetryPolicy
from agent_connector_sdk.tls.resolve import resolve_tls_profile

__all__ = [
    "ApiKey",
    "AuthConfigurationError",
    "AuthDeclaration",
    "Basic",
    "Bearer",
    "BuildContext",
    "ClientCredentials",
    "ManagedClient",
    "NoAuth",
    "RefreshToken",
    "SessionLogin",
    "client_factory",
    "open_client",
]


class AuthConfigurationError(AuthError):
    """A declaration is incomplete or names an unavailable setting; no values."""


def _reference(env: str, ref: str, what: str) -> str:
    if bool(env) == bool(ref):
        raise AuthConfigurationError(f"{what} needs exactly one of env or ref")
    return ref or f"env://{env}"


@dataclass(frozen=True)
class BuildContext:
    """What a declaration needs to build its ``httpx.Auth``."""

    base_url: str
    token_client: httpx.Client
    resolver: CredentialResolver | None


class AuthDeclaration(Protocol):
    """A one-line declaration of how a connector authenticates."""

    def build(self, context: BuildContext) -> httpx.Auth | None:
        """The ``httpx.Auth`` for this scheme, ``None`` for no authentication."""
        ...


@dataclass(frozen=True)
class NoAuth:
    """No outbound authentication (local tools, public APIs)."""

    def build(self, context: BuildContext) -> httpx.Auth | None:
        return None


@dataclass(frozen=True)
class Bearer:
    """``Authorization: Bearer`` from a static token."""

    env: str = ""
    ref: str = ""

    def build(self, context: BuildContext) -> httpx.Auth | None:
        reference = _reference(self.env, self.ref, "Bearer")
        return RotatingAuth(
            lambda: resolved_credential(reference, context.resolver),
            lambda request, secret: request.headers.__setitem__(
                "Authorization", f"Bearer {secret}"
            ),
        )


@dataclass(frozen=True)
class ApiKey:
    """An API key in a header (with an optional prefix) or a query parameter."""

    env: str = ""
    ref: str = ""
    header: str = ""
    query: str = ""
    prefix: str = ""

    def build(self, context: BuildContext) -> httpx.Auth | None:
        reference = _reference(self.env, self.ref, "ApiKey")
        if bool(self.header) == bool(self.query):
            raise AuthConfigurationError("ApiKey needs exactly one of header or query")
        header, query, prefix = self.header, self.query, self.prefix

        def apply(request: httpx.Request, secret: str) -> None:
            if header:
                request.headers[header] = f"{prefix}{secret}"
            else:
                request.url = request.url.copy_merge_params({query: secret})

        return RotatingAuth(
            lambda: resolved_credential(reference, context.resolver),
            apply,
            isolates_cookies=True,
        )


@dataclass(frozen=True)
class Basic:
    """HTTP Basic with a literal or environment-named user and a secret password."""

    password_env: str = ""
    password_ref: str = ""
    user_env: str = ""
    user: str = ""

    def build(self, context: BuildContext) -> httpx.Auth | None:
        reference = _reference(self.password_env, self.password_ref, "Basic")
        username = self.user or _setting_value(self.user_env, "Basic user")
        if ":" in username:
            raise AuthConfigurationError("Basic user must not contain ':'")

        def apply(request: httpx.Request, secret: str) -> None:
            token = base64.b64encode(f"{username}:{secret}".encode()).decode("ascii")
            request.headers["Authorization"] = f"Basic {token}"

        return RotatingAuth(
            lambda: resolved_credential(reference, context.resolver), apply
        )


@dataclass(frozen=True)
class ClientCredentials:
    """OAuth 2.0 client credentials; discovers the endpoint from ``issuer``."""

    client_id: str = ""
    client_id_env: str = ""
    secret_env: str = ""
    secret_ref: str = ""
    token_url: str = ""
    issuer: str = ""
    audience: str = ""
    scope: str = ""

    def build(self, context: BuildContext) -> httpx.Auth | None:
        reference = _reference(self.secret_env, self.secret_ref, "ClientCredentials")
        client_id = self.client_id or _setting_value(self.client_id_env, "client id")
        token_url = _token_url(self.token_url, self.issuer, context)
        provider = ClientCredentialsTokenProvider(
            token_url=token_url,
            client_id=client_id,
            client_secret_ref=reference,
            http_client=context.token_client,
            audience=self.audience,
            scope=self.scope,
            resolver=context.resolver,
        )
        return ClientCredentialsAuth(provider)


@dataclass(frozen=True)
class RefreshToken:
    """OAuth 2.0 refresh-token grant (auth-code flows after the one-time consent)."""

    refresh_env: str = ""
    refresh_ref: str = ""
    client_id: str = ""
    client_id_env: str = ""
    secret_env: str = ""
    secret_ref: str = ""
    token_url: str = ""
    issuer: str = ""
    scope: str = ""

    def build(self, context: BuildContext) -> httpx.Auth | None:
        refresh = _reference(self.refresh_env, self.refresh_ref, "RefreshToken")
        client_auth_ref = ""
        if self.secret_env or self.secret_ref:
            client_auth_ref = _reference(
                self.secret_env, self.secret_ref, "RefreshToken secret"
            )
        provider = RefreshTokenProvider(
            token_url=_token_url(self.token_url, self.issuer, context),
            client_id=self.client_id or _setting_value(self.client_id_env, "client id"),
            refresh_token_ref=refresh,
            client_secret_ref=client_auth_ref,
            http_client=context.token_client,
            scope=self.scope,
            resolver=context.resolver,
        )
        return ClientCredentialsAuth(provider)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SessionLogin:
    """Cookie-session login against ``login_path`` with re-login on 401/403."""

    login_path: str
    user_env: str = ""
    user: str = ""
    password_env: str = ""
    password_ref: str = ""
    username_field: str = "username"
    password_field: str = "password"

    def build(self, context: BuildContext) -> httpx.Auth | None:
        reference = _reference(self.password_env, self.password_ref, "SessionLogin")
        return SessionLoginAuth(
            login_path=self.login_path,
            username=self.user or _setting_value(self.user_env, "session user"),
            password=lambda: resolve_secret_reference(reference, context.resolver),
            username_field=self.username_field,
            password_field=self.password_field,
        )


def _setting_value(name: str, what: str) -> str:
    value = setting(name, "") if name else ""
    if not isinstance(value, str) or not value:
        raise AuthConfigurationError(f"{what} setting is not set")
    return value


def _token_url(token_url: str, issuer: str, context: BuildContext) -> str:
    if bool(token_url) == bool(issuer):
        raise AuthConfigurationError("OAuth needs exactly one of token_url or issuer")
    return token_url or discover_token_endpoint(issuer, context.token_client)


@dataclass
class ManagedClient:
    """A built client and the resources (TLS files, token client) it owns."""

    client: httpx.Client
    _resources: ExitStack = field(repr=False)

    def close(self) -> None:
        """Close the client, the token client and remove TLS runtime files."""
        self._resources.close()

    def __enter__(self) -> ManagedClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def open_client(
    *,
    base_url: str,
    auth: AuthDeclaration,
    tls: str,
    delegation: bool = False,
    allow_plaintext: bool = False,
    headers: Mapping[str, str] | None = None,
    retry: RetryPolicy | None = None,
    resolver: CredentialResolver | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ManagedClient:
    """Build the governed client for ``base_url`` from a declaration.

    With ``delegation`` and ``ENABLE_DELEGATION`` set, the caller's verified
    token is exchanged per request (RFC 8693) instead of ``auth``.

    Raises:
        AuthConfigurationError: the declaration is incomplete.
        TransportSecurityError: the TLS profile is invalid.
    """
    resources = ExitStack()
    try:
        profile = resolve_tls_profile(tls, resolver=resolver)
        resources.callback(profile.cleanup)
        origin = urlsplit(base_url)
        token_client = create_http_client(
            HttpClientOptions(
                base_url=f"{origin.scheme}://{origin.netloc}",
                tls=profile,
                allow_plaintext=allow_plaintext,
            )
        )
        resources.callback(token_client.close)
        context = BuildContext(base_url, token_client, resolver)
        settings = DelegationSettings.from_settings() if delegation else None
        if settings is not None and settings.enabled:
            built: httpx.Auth | None = DelegatedTokenAuth(
                settings, http_client=token_client, resolver=resolver
            )
        else:
            built = auth.build(context)
        client = create_http_client(
            HttpClientOptions(
                base_url=base_url,
                tls=profile,
                auth=built,
                headers=dict(headers or {}),
                retry=retry or RetryPolicy(),
                allow_plaintext=allow_plaintext,
            ),
            transport=transport,
        )
        resources.callback(client.close)
        return ManagedClient(client, resources)
    except BaseException:
        resources.close()
        raise


def client_factory(
    *,
    url_env: str,
    auth: AuthDeclaration,
    tls: str,
    delegation: bool = False,
    allow_plaintext_env: str = "",
    headers: Mapping[str, str] | None = None,
) -> Callable[[], httpx.Client]:
    """A ``get_client()`` that builds the declared client once and reuses it.

    Raises (when called):
        AuthConfigurationError: ``url_env`` is not set or the declaration is
            incomplete.
    """
    lock = threading.Lock()
    holder: list[ManagedClient] = []

    def get_client() -> httpx.Client:
        with lock:
            if not holder:
                url = setting(url_env, "")
                if not isinstance(url, str) or not url:
                    raise AuthConfigurationError(f"{url_env} is not set")
                plaintext = (
                    bool(setting(allow_plaintext_env, False))
                    if allow_plaintext_env
                    else False
                )
                holder.append(
                    open_client(
                        base_url=url.rstrip("/"),
                        auth=auth,
                        tls=tls,
                        delegation=delegation,
                        allow_plaintext=plaintext,
                        headers=headers,
                    )
                )
            return holder[0].client

    def close_client() -> None:
        with lock:
            while holder:
                holder.pop().close()

    get_client.close = close_client  # type: ignore[attr-defined]
    return get_client
