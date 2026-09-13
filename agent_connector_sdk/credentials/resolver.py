"""The credential resolver port and the environment and per-scheme resolvers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.references import SecretReference

__all__ = [
    "CompositeCredentialResolver",
    "CredentialResolver",
    "CredentialUnavailableError",
    "EnvironmentCredentialResolver",
]


class CredentialUnavailableError(RuntimeError):
    """A well-formed secret reference could not be resolved to a usable value."""


class CredentialResolver(Protocol):
    """Resolves one parsed reference to its secret value."""

    def resolve(self, reference: SecretReference) -> str:
        """Return the value or raise :class:`CredentialUnavailableError`."""
        ...


class EnvironmentCredentialResolver:
    """Resolves ``env://`` references from the process environment."""

    def resolve(self, reference: SecretReference) -> str:
        """Return the named environment variable's value."""
        value = setting(reference.target) if reference.scheme == "env" else None
        if not isinstance(value, str) or not value:
            raise CredentialUnavailableError("secret reference is unavailable")
        return value


class CompositeCredentialResolver:
    """Dispatches each reference to the resolver registered for its scheme."""

    def __init__(self, resolvers: Mapping[str, CredentialResolver]) -> None:
        self._resolvers = dict(resolvers)

    def resolve(self, reference: SecretReference) -> str:
        """Resolve through the scheme's resolver; an unknown scheme fails."""
        resolver = self._resolvers.get(reference.scheme)
        if resolver is None:
            raise CredentialUnavailableError(
                f"no credential resolver is configured for {reference.scheme}://"
            )
        return resolver.resolve(reference)
