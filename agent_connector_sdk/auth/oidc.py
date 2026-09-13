"""Client-credentials configuration for an OIDC issuer, for APIs and MCP endpoints.

The same configuration authenticates a connector to a vendor API and the
connector-sync runner or ``connector-certify`` to a fleet MCP server. It matches
the service identity graph-os presents to fleet servers: the
``client_credentials`` grant with HTTP Basic client authentication, an
``audience`` the servers verify and optional scopes, against a token endpoint
set directly or discovered from the issuer.

Settings read by :meth:`ClientCredentialsConfig.from_settings`:

- ``OIDC_ISSUER``: the issuer (the first of a comma-separated list), or
- ``OIDC_TOKEN_URL``: the token endpoint, instead of discovery;
- ``OIDC_CLIENT_ID`` and ``OIDC_CLIENT_SECRET_REF`` (a secret reference);
- ``OIDC_AUDIENCE`` and ``OIDC_SCOPE`` (space-separated).
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_connector_sdk.auth.client_credentials import (
    ClientCredentialsAuth,
    ClientCredentialsTokenProvider,
)
from agent_connector_sdk.auth.tokens import TokenRequestError
from agent_connector_sdk.config import csv_values, setting
from agent_connector_sdk.credentials.references import parse_secret_reference
from agent_connector_sdk.credentials.resolver import CredentialResolver
from agent_connector_sdk.http.client import create_http_client
from agent_connector_sdk.http.errors import HttpProblemError
from agent_connector_sdk.http.options import HttpClientOptions
from agent_connector_sdk.http.responses import request_json
from agent_connector_sdk.tls.profile import ResolvedTLSProfile

__all__ = [
    "ClientCredentialsConfig",
    "client_credentials_auth",
    "discover_token_endpoint",
]

_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


def _endpoint_problem(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return "must be an absolute http or https URL"
    if parts.scheme == "http" and parts.hostname not in _LOOPBACK:
        return "must use https outside loopback"
    if parts.username or parts.password or parts.query or parts.fragment:
        return "must not carry credentials, a query or a fragment"
    return None


class ClientCredentialsConfig(BaseModel):
    """Where and as whom to obtain client-credentials tokens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    issuer: str = ""
    token_url: str = ""
    client_id: str = Field(min_length=1, max_length=4_096, pattern=r"^[^\r\n\x00]+$")
    client_secret_ref: str
    audience: str = Field(default="", max_length=2_048)
    scope: str = Field(default="", max_length=4_096)

    @model_validator(mode="after")
    def _check(self) -> ClientCredentialsConfig:
        if bool(self.issuer) == bool(self.token_url):
            raise ValueError(
                "client credentials need exactly one of issuer or token_url"
            )
        problem = _endpoint_problem(self.issuer or self.token_url)
        if problem is not None:
            raise ValueError(f"client credentials issuer or token_url {problem}")
        parse_secret_reference(self.client_secret_ref)
        return self

    @classmethod
    def from_settings(cls) -> ClientCredentialsConfig:
        """Read the settings in the module docstring.

        Raises:
            pydantic.ValidationError: a setting is missing or invalid.
        """
        issuers = csv_values(setting("OIDC_ISSUER", ""))
        return cls(
            issuer=issuers[0] if issuers else "",
            token_url=str(setting("OIDC_TOKEN_URL", "")),
            client_id=str(setting("OIDC_CLIENT_ID", "")),
            client_secret_ref=str(setting("OIDC_CLIENT_SECRET_REF", "")),
            audience=str(setting("OIDC_AUDIENCE", "")),
            scope=str(setting("OIDC_SCOPE", "")),
        )


def discover_token_endpoint(issuer: str, http_client: httpx.Client) -> str:
    """The ``token_endpoint`` of ``issuer``'s OIDC discovery document.

    Raises:
        TokenRequestError: discovery failed or named an unusable endpoint.
    """
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        document = request_json(http_client, "GET", url, max_bytes=256_000)
    except (HttpProblemError, httpx.HTTPError) as exc:
        raise TokenRequestError("OIDC discovery failed") from exc
    endpoint = document.get("token_endpoint") if isinstance(document, dict) else None
    if not isinstance(endpoint, str) or _endpoint_problem(endpoint) is not None:
        raise TokenRequestError("OIDC discovery returned no usable token_endpoint")
    return endpoint


def client_credentials_auth(
    config: ClientCredentialsConfig,
    *,
    resolver: CredentialResolver | None = None,
    tls: ResolvedTLSProfile | None = None,
) -> ClientCredentialsAuth:
    """An ``httpx.Auth`` for ``config``, usable by API clients and MCP endpoints.

    The issuer's token endpoint is discovered here; tokens are minted on first
    use, cached, refreshed before expiry and re-minted once on a 401.

    Raises:
        TokenRequestError: discovery failed.
    """
    origin = urlsplit(config.issuer or config.token_url)
    client = create_http_client(
        HttpClientOptions(base_url=f"{origin.scheme}://{origin.netloc}", tls=tls)
    )
    token_url = config.token_url or discover_token_endpoint(config.issuer, client)
    provider = ClientCredentialsTokenProvider(
        token_url=token_url,
        client_id=config.client_id,
        client_secret_ref=config.client_secret_ref,
        http_client=client,
        audience=config.audience,
        scope=config.scope,
        resolver=resolver,
    )
    return ClientCredentialsAuth(provider)
