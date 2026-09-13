"""Shared authentication inputs, URL policy, secret resolution and discovery."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

import httpx

from agent_connector_sdk.config import csv_values
from agent_connector_sdk.credentials.references import SecretReferenceError
from agent_connector_sdk.credentials.resolution import resolve_secret_reference
from agent_connector_sdk.credentials.resolver import (
    CredentialResolver,
    CredentialUnavailableError,
)

__all__ = [
    "AUTH_TYPES",
    "AuthConfigurationError",
    "AuthInputs",
    "allowed_redirect_uris",
    "discover_jwks_uri",
    "resolve_auth_secret",
    "secure_auth_url",
]

AUTH_TYPES = ("none", "static", "jwt", "oauth-proxy", "oidc-proxy", "remote-oauth")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_MAX_REDIRECT_URIS = 32


class AuthConfigurationError(ValueError):
    """The requested authentication mode is misconfigured or unsupported."""


@dataclass(frozen=True)
class AuthInputs:
    """Everything an auth provider builder needs."""

    args: argparse.Namespace
    resolver: CredentialResolver | None = None
    http_client: httpx.Client | None = None


def _is_malformed(parsed: SplitResult, rendered: str) -> bool:
    return (
        len(rendered) > 8_192
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
    )


def secure_auth_url(value: object, *, field: str) -> str:
    """Validate an authentication URL: http(s), no credentials, HTTPS off loopback.

    Raises:
        AuthConfigurationError: for any other URL.
    """
    rendered = str(value or "").strip()
    parsed = urlsplit(rendered)
    if _is_malformed(parsed, rendered):
        raise AuthConfigurationError(f"{field} is invalid")
    if parsed.scheme == "http" and (parsed.hostname or "") not in _LOOPBACK_HOSTS:
        raise AuthConfigurationError(f"{field} requires HTTPS outside loopback")
    return rendered


def resolve_auth_secret(reference: object, inputs: AuthInputs, *, what: str) -> str:
    """Resolve an auth secret reference or raise a configuration error."""
    try:
        return resolve_secret_reference(str(reference or ""), inputs.resolver)
    except (SecretReferenceError, CredentialUnavailableError) as exc:
        raise AuthConfigurationError(f"{what} reference is unavailable") from exc


def allowed_redirect_uris(args: argparse.Namespace) -> list[str] | None:
    """The validated ``--allowed-client-redirect-uris`` list, or ``None``."""
    uris = csv_values(args.allowed_client_redirect_uris)
    if len(uris) > _MAX_REDIRECT_URIS:
        raise AuthConfigurationError("too many allowed client redirect URIs")
    return [secure_auth_url(uri, field="redirect URI") for uri in uris] or None


def discover_jwks_uri(issuer: str, *, http_client: httpx.Client | None = None) -> str:
    """Resolve an issuer's ``jwks_uri`` from its OIDC discovery document.

    Raises:
        AuthConfigurationError: discovery failed or returned no valid URI.
    """
    base = secure_auth_url(issuer, field="JWT issuer").rstrip("/")
    client = http_client or httpx.Client(timeout=10.0)
    try:
        response = client.get(f"{base}/.well-known/openid-configuration")
        document = response.raise_for_status().json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AuthConfigurationError("OIDC discovery failed") from exc
    jwks_uri = document.get("jwks_uri") if isinstance(document, dict) else None
    return secure_auth_url(jwks_uri, field="discovered JWKS URI")
