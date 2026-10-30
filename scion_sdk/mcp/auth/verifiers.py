"""Hardened JWT token verifiers."""

from __future__ import annotations

import math
import time
from typing import Any

from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier

__all__ = ["any_realm_verifier", "claims_are_current", "hardened_jwt_verifier"]

_MAX_TOKEN_BYTES = 16_384
_CLOCK_SKEW_SECONDS = 30.0


def _finite_time(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def claims_are_current(claims: dict[str, Any], now: float) -> bool:
    """``exp`` is present and in the future; ``nbf``/``iat`` are not in the future."""
    expiry = _finite_time(claims.get("exp"))
    if expiry is None or expiry < now:
        return False
    for name in ("nbf", "iat"):
        if name not in claims:
            continue
        issued = _finite_time(claims[name])
        if issued is None or issued > now + _CLOCK_SKEW_SECONDS:
            return False
    return True


class _HardenedJWTVerifier(JWTVerifier):
    async def verify_token(self, token: str) -> Any:
        if not token or len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
            return None
        result = await super().verify_token(token)
        claims = getattr(result, "claims", None)
        if not isinstance(claims, dict) or not claims_are_current(claims, time.time()):
            return None
        return result


def hardened_jwt_verifier(**kwargs: Any) -> JWTVerifier:
    """FastMCP's JWT verifier with bounded tokens and a mandatory current ``exp``."""
    return _HardenedJWTVerifier(**kwargs)


class _AnyRealmVerifier(TokenVerifier):
    def __init__(
        self, verifiers: list[Any], *, required_scopes: list[str] | None
    ) -> None:
        super().__init__(required_scopes=required_scopes)
        self._verifiers = list(verifiers)

    async def verify_token(self, token: str) -> Any:
        for verifier in self._verifiers:
            result = await verifier.verify_token(token)
            if result is not None:
                return result
        return None


def any_realm_verifier(
    verifiers: list[Any], *, required_scopes: list[str] | None
) -> TokenVerifier:
    """Accept a token that any one realm's verifier accepts (realm migration)."""
    return _AnyRealmVerifier(verifiers, required_scopes=required_scopes)
