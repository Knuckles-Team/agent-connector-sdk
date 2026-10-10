"""A credential provider scoped to one connector's identity.

:class:`~agent_connector_sdk.credentials.resolver.CredentialResolver` resolves
a parsed reference to its value with no notion of *who* is asking.
:class:`CredentialProvider` (SDK-CONNECTOR-CONTROL-R035) wraps a resolver with
the requesting connector's own identity: an ``openbao://`` reference whose
path is not that connector's own is refused before any resolver call, and the
resolved value is returned once per call -- never retained, logged, or
echoed by this provider.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_connector_sdk.credentials.references import SecretReference
from agent_connector_sdk.credentials.resolver import CredentialResolver

__all__ = ["CredentialProvider", "CredentialScopeError"]


class CredentialScopeError(PermissionError):
    """A reference's scope does not match the requesting connector."""


@dataclass(frozen=True)
class CredentialProvider:
    """Resolves one secret reference, scoped to ``connector``'s identity."""

    resolver: CredentialResolver
    connector: str

    def get_secret(self, reference: SecretReference) -> str:
        """Return the resolved secret value for ``reference``.

        ``env://`` references are process-wide and always in scope.
        ``openbao://mount/path#field`` references must have ``path`` equal
        to, or nested under, this provider's own ``connector`` (the
        convention a shared mount such as ``apps`` uses to separate
        connectors, e.g. ``openbao://apps/freshrss-agent#TOKEN``).

        Raises:
            CredentialScopeError: an ``openbao://`` reference's path is not
                ``self.connector`` or a path nested under it.
            CredentialUnavailableError: the underlying resolver could not
                resolve the reference (raised by ``self.resolver``).
        """
        in_scope = reference.path == self.connector or reference.path.startswith(
            f"{self.connector}/"
        )
        if reference.scheme == "openbao" and not in_scope:
            raise CredentialScopeError(
                "secret reference is outside the requesting connector's scope"
            )
        return self.resolver.resolve(reference)
