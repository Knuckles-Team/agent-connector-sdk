"""The shared token cache behind the OAuth grant providers."""

from __future__ import annotations

import time

import pytest

from scion_sdk.auth import client_credentials
from scion_sdk.auth._cached_provider import (
    REFRESH_SKEW_SECONDS,
    CachedTokenProvider,
    resolve_or_unavailable,
)
from scion_sdk.auth.tokens import AccessToken, TokenRequestError


class _Counting(CachedTokenProvider):
    def __init__(self) -> None:
        super().__init__(self._mint)
        self.mints = 0

    def _mint(self) -> AccessToken:
        self.mints += 1
        return AccessToken(
            value=f"t{self.mints}",
            ttl_seconds=3600.0,
            expires_at=time.monotonic() + 3600.0,
        )


def test_token_is_cached_until_forced() -> None:
    provider = _Counting()
    assert provider.get_token() == "t1"
    assert provider.get_token() == "t1"
    assert provider.get_token(force=True) == "t2"


def test_skew_constant_is_shared() -> None:
    assert client_credentials.REFRESH_SKEW_SECONDS == REFRESH_SKEW_SECONDS == 30.0


def test_unresolvable_reference_is_a_token_request_error() -> None:
    with pytest.raises(TokenRequestError, match="client secret is unavailable"):
        resolve_or_unavailable("env://SCION_QD_DEFINITELY_UNSET", None, "client secret")
