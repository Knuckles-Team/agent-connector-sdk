"""OAuth proxy, OIDC proxy and remote OAuth providers."""

from __future__ import annotations

from typing import Any

from fastmcp.server.auth import OAuthProxy, RemoteAuthProvider
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from pydantic import AnyHttpUrl

from agent_connector_sdk.config import csv_values
from agent_connector_sdk.mcp.auth.policy import (
    AuthConfigurationError,
    AuthInputs,
    allowed_redirect_uris,
    resolve_auth_secret,
    secure_auth_url,
)
from agent_connector_sdk.mcp.auth.verifiers import hardened_jwt_verifier

__all__ = ["configure_oauth_proxy", "configure_oidc_proxy", "configure_remote_oauth"]

_MAX_AUTHORIZATION_SERVERS = 16


def _require(inputs: AuthInputs, names: tuple[str, ...], mode: str) -> None:
    missing = [name for name in names if not getattr(inputs.args, name)]
    if missing:
        raise AuthConfigurationError(f"{mode} requires {', '.join(missing)}")


def _upstream_verifier(inputs: AuthInputs) -> Any:
    return hardened_jwt_verifier(
        jwks_uri=secure_auth_url(inputs.args.token_jwks_uri, field="JWKS URI"),
        issuer=secure_auth_url(inputs.args.token_issuer, field="JWT issuer"),
        audience=inputs.args.token_audience,
    )


def configure_oauth_proxy(inputs: AuthInputs) -> OAuthProxy:
    """OAuth proxy in front of an upstream authorization server."""
    _require(
        inputs,
        (
            "oauth_upstream_auth_endpoint",
            "oauth_upstream_token_endpoint",
            "oauth_upstream_client_id",
            "oauth_upstream_client_secret_ref",
            "oauth_base_url",
            "token_jwks_uri",
            "token_issuer",
            "token_audience",
        ),
        "oauth-proxy",
    )
    args = inputs.args
    return OAuthProxy(
        upstream_authorization_endpoint=secure_auth_url(
            args.oauth_upstream_auth_endpoint, field="OAuth authorization endpoint"
        ),
        upstream_token_endpoint=secure_auth_url(
            args.oauth_upstream_token_endpoint, field="OAuth token endpoint"
        ),
        upstream_client_id=args.oauth_upstream_client_id,
        upstream_client_secret=resolve_auth_secret(
            args.oauth_upstream_client_secret_ref, inputs, what="OAuth client secret"
        ),
        token_verifier=_upstream_verifier(inputs),
        base_url=secure_auth_url(args.oauth_base_url, field="OAuth base URL"),
        allowed_client_redirect_uris=allowed_redirect_uris(args),
    )


def configure_oidc_proxy(inputs: AuthInputs) -> OIDCProxy:
    """OIDC proxy configured from a discovery document."""
    _require(
        inputs,
        (
            "oidc_config_url",
            "oidc_client_id",
            "oidc_client_secret_ref",
            "oidc_base_url",
            "token_audience",
        ),
        "oidc-proxy",
    )
    args = inputs.args
    return OIDCProxy(
        config_url=secure_auth_url(
            args.oidc_config_url, field="OIDC configuration URL"
        ),
        client_id=args.oidc_client_id,
        client_secret=resolve_auth_secret(
            args.oidc_client_secret_ref, inputs, what="OIDC client secret"
        ),
        audience=args.token_audience,
        base_url=secure_auth_url(args.oidc_base_url, field="OIDC base URL"),
        allowed_client_redirect_uris=allowed_redirect_uris(args),
    )


def configure_remote_oauth(inputs: AuthInputs) -> RemoteAuthProvider:
    """Token verification against remote authorization servers."""
    _require(
        inputs,
        (
            "remote_auth_servers",
            "remote_base_url",
            "token_jwks_uri",
            "token_issuer",
            "token_audience",
        ),
        "remote-oauth",
    )
    servers = [
        secure_auth_url(value, field="authorization server")
        for value in csv_values(inputs.args.remote_auth_servers)
    ]
    if len(servers) > _MAX_AUTHORIZATION_SERVERS:
        raise AuthConfigurationError("too many remote authorization servers")
    return RemoteAuthProvider(
        token_verifier=_upstream_verifier(inputs),
        authorization_servers=[AnyHttpUrl(server) for server in servers],
        base_url=secure_auth_url(
            inputs.args.remote_base_url, field="remote OAuth base URL"
        ),
    )
