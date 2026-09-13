"""Static bearer tokens from a secret reference, verified in constant time."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastmcp.server.auth import AccessToken, TokenVerifier

from agent_connector_sdk.mcp.auth.policy import (
    AuthConfigurationError,
    AuthInputs,
    resolve_auth_secret,
)
from agent_connector_sdk.mcp.auth.verifiers import claims_are_current

__all__ = ["configure_static_auth", "validated_static_tokens"]

_MIN_TOKEN_LENGTH = 32
_MAX_TOKEN_LENGTH = 4_096


def _identity_is_valid(client_id: object, scopes: object) -> bool:
    return (
        isinstance(client_id, str)
        and 1 <= len(client_id) <= 256
        and isinstance(scopes, list)
        and all(isinstance(scope, str) and scope for scope in scopes)
    )


def _static_entry(token: str, claims: object) -> dict[str, Any]:
    if (
        not isinstance(claims, dict)
        or not _MIN_TOKEN_LENGTH <= len(token) <= _MAX_TOKEN_LENGTH
    ):
        raise AuthConfigurationError("static token entry is invalid")
    entry: dict[str, Any] = {
        "client_id": claims.get("client_id"),
        "scopes": claims.get("scopes", []),
    }
    if not _identity_is_valid(entry["client_id"], entry["scopes"]):
        raise AuthConfigurationError("static token client_id or scopes are invalid")
    if "expires_at" not in claims:
        return entry
    if not claims_are_current({"exp": claims["expires_at"]}, float("-inf")):
        raise AuthConfigurationError("static token expiry is invalid")
    return {**entry, "expires_at": claims["expires_at"]}


def validated_static_tokens(raw: str) -> dict[str, dict[str, Any]]:
    """Parse and validate the static token map ``{token: {client_id, scopes}}``.

    Raises:
        AuthConfigurationError: the map is not JSON, empty, or has a bad entry.
    """
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthConfigurationError("static token map is not JSON") from exc
    if not isinstance(document, dict) or not document:
        raise AuthConfigurationError("static token map is empty")
    return {
        str(token): _static_entry(str(token), claims)
        for token, claims in document.items()
    }


class _ConstantTimeStaticVerifier(TokenVerifier):
    def __init__(self, tokens: dict[str, dict[str, Any]]) -> None:
        super().__init__()
        self._key = secrets.token_bytes(32)
        self._entries = [(self._mac(token), claims) for token, claims in tokens.items()]

    def _mac(self, token: str) -> bytes:
        return hmac.new(self._key, token.encode("utf-8"), hashlib.sha256).digest()

    async def verify_token(self, token: str) -> Any:
        candidate = self._mac(token[: _MAX_TOKEN_LENGTH + 1])
        matched = [
            claims
            for expected, claims in self._entries
            if secrets.compare_digest(candidate, expected)
        ]
        expires_at = matched[0].get("expires_at") if matched else None
        if not matched or (expires_at is not None and float(expires_at) < time.time()):
            return None
        return AccessToken(
            token=token,
            client_id=matched[0]["client_id"],
            scopes=list(matched[0]["scopes"]),
            expires_at=int(expires_at) if expires_at is not None else None,
            claims=matched[0],
        )


def configure_static_auth(inputs: AuthInputs) -> TokenVerifier:
    """Build the static-token verifier from ``--static-tokens-ref``."""
    if not inputs.args.static_tokens_ref:
        raise AuthConfigurationError("static auth requires --static-tokens-ref")
    raw = resolve_auth_secret(
        inputs.args.static_tokens_ref, inputs, what="static token map"
    )
    return _ConstantTimeStaticVerifier(validated_static_tokens(raw))
