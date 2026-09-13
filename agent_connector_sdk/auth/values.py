"""Validation for credential values that travel in HTTP headers."""

from __future__ import annotations

from agent_connector_sdk.credentials.resolution import resolve_secret_reference
from agent_connector_sdk.credentials.resolver import (
    CredentialResolver,
    CredentialUnavailableError,
)

__all__ = ["header_safe", "resolved_credential"]

_FORBIDDEN = frozenset("\r\n\x00")


def header_safe(value: str, *, what: str) -> str:
    """Return ``value`` when it can travel in a header, else raise ``ValueError``."""
    if not value or _FORBIDDEN.intersection(value):
        raise ValueError(f"{what} is empty or holds a control character")
    return value


def resolved_credential(reference: str, resolver: CredentialResolver | None) -> str:
    """Resolve ``reference`` to a value that can travel in a header.

    Raises:
        SecretReferenceError: the reference is malformed.
        CredentialUnavailableError: the value is missing or holds CR, LF or NUL.
    """
    value = resolve_secret_reference(reference, resolver)
    if _FORBIDDEN.intersection(value):
        raise CredentialUnavailableError("resolved credential is invalid")
    return value
