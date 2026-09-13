"""JWT authentication, single-realm or multi-realm, with RFC 9728 metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp.server.auth import RemoteAuthProvider
from pydantic import AnyHttpUrl

from agent_connector_sdk.config import csv_values
from agent_connector_sdk.mcp.auth.policy import (
    AuthConfigurationError,
    AuthInputs,
    discover_jwks_uri,
    resolve_auth_secret,
    secure_auth_url,
)
from agent_connector_sdk.mcp.auth.verifiers import (
    any_realm_verifier,
    hardened_jwt_verifier,
)

__all__ = ["configure_jwt_auth"]

_MIN_HMAC_SECRET_BYTES = 32


def _key_material(inputs: AuthInputs) -> str | None:
    args = inputs.args
    if str(args.token_algorithm or "").startswith("HS"):
        if not args.token_secret_ref:
            raise AuthConfigurationError(
                "HMAC JWT verification requires --token-secret-ref"
            )
        secret = resolve_auth_secret(
            args.token_secret_ref, inputs, what="JWT HMAC secret"
        )
        if len(secret.encode("utf-8")) < _MIN_HMAC_SECRET_BYTES:
            raise AuthConfigurationError("JWT HMAC secret is too short")
        return secret
    key = str(args.token_public_key or "")
    return (
        Path(key).read_text(encoding="utf-8")
        if key and Path(key).is_file()
        else key or None
    )


def _jwks_uris(inputs: AuthInputs, issuers: list[str], key: str | None) -> list[str]:
    explicit = [
        secure_auth_url(value, field="JWKS URI")
        for value in csv_values(inputs.args.token_jwks_uri)
    ]
    if explicit or key is not None:
        return explicit
    return [
        discover_jwks_uri(issuer, http_client=inputs.http_client) for issuer in issuers
    ]


def _with_resource_metadata(
    verifier: Any, inputs: AuthInputs, issuers: list[str]
) -> Any:
    """Publish RFC 9728 protected-resource metadata when a public URL is set."""
    if not inputs.args.public_base_url:
        return verifier
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl(issuer) for issuer in issuers],
        base_url=secure_auth_url(
            inputs.args.public_base_url, field="MCP public base URL"
        ),
    )


def _multi_realm(inputs: AuthInputs, issuers: list[str], jwks_uris: list[str]) -> Any:
    if len(issuers) != len(jwks_uris):
        raise AuthConfigurationError(
            "multi-realm JWT needs equally long issuer and JWKS lists"
        )
    scopes = csv_values(inputs.args.required_scopes) or None
    verifiers = [
        hardened_jwt_verifier(
            jwks_uri=jwks_uri,
            issuer=issuer,
            audience=inputs.args.token_audience,
            algorithm=inputs.args.token_algorithm or "RS256",
            required_scopes=scopes,
        )
        for jwks_uri, issuer in zip(jwks_uris, issuers, strict=True)
    ]
    return any_realm_verifier(verifiers, required_scopes=scopes)


def _issuers(inputs: AuthInputs) -> list[str]:
    issuers = [
        secure_auth_url(value, field="JWT issuer")
        for value in csv_values(inputs.args.token_issuer)
    ]
    audience = str(inputs.args.token_audience or "")
    if not issuers or not 1 <= len(audience) <= 512:
        raise AuthConfigurationError(
            "JWT auth requires --token-issuer and --token-audience"
        )
    return issuers


def _single_realm(inputs: AuthInputs, jwks_uris: list[str], key: str | None) -> Any:
    args = inputs.args
    return hardened_jwt_verifier(
        jwks_uri=jwks_uris[0] if jwks_uris else None,
        public_key=None if jwks_uris else key,
        issuer=csv_values(args.token_issuer)[0],
        audience=args.token_audience,
        algorithm=args.token_algorithm or "RS256",
        required_scopes=csv_values(args.required_scopes) or None,
    )


def configure_jwt_auth(inputs: AuthInputs) -> Any:
    """Build the JWT verifier from ``--token-*`` settings.

    Raises:
        AuthConfigurationError: issuer or audience missing, key material
            unavailable, or issuer and JWKS lists misaligned.
    """
    issuers = _issuers(inputs)
    key = _key_material(inputs)
    jwks_uris = _jwks_uris(inputs, issuers, key)
    if len(issuers) > 1 or len(jwks_uris) > 1:
        verifier = _multi_realm(inputs, issuers, jwks_uris)
    else:
        verifier = _single_realm(inputs, jwks_uris, key)
    return _with_resource_metadata(verifier, inputs, issuers)
