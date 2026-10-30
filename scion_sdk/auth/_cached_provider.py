"""Shared token-cache machinery for the OAuth grant providers."""

from __future__ import annotations

import threading

from scion_sdk.auth.tokens import AccessToken, TokenRequestError
from scion_sdk.credentials.references import SecretReferenceError
from scion_sdk.credentials.resolution import resolve_secret_reference
from scion_sdk.credentials.resolver import (
    CredentialResolver,
    CredentialUnavailableError,
)

#: Refresh a cached token this many seconds before it expires.
REFRESH_SKEW_SECONDS = 30.0


def resolve_or_unavailable(
    reference: str, resolver: CredentialResolver | None, what: str
) -> str:
    """Resolve ``reference``, mapping resolution failures to ``TokenRequestError``."""
    try:
        return resolve_secret_reference(reference, resolver)
    except (SecretReferenceError, CredentialUnavailableError) as exc:
        raise TokenRequestError(f"{what} is unavailable") from exc


class CachedTokenProvider:
    """A thread-safe token cache; subclasses implement ``_mint``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: AccessToken | None = None

    def _mint(self) -> AccessToken:
        raise NotImplementedError

    def get_token(self, *, force: bool = False) -> str:
        """A cached token, minted when missing, near expiry or ``force``d.

        Raises:
            TokenRequestError: minting failed.
        """
        with self._lock:
            if (
                force
                or self._token is None
                or not self._token.fresh(REFRESH_SKEW_SECONDS)
            ):
                self._token = self._mint()
            return self._token.value
