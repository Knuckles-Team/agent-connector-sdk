"""Build transport endpoints from descriptors, resolving credentials first."""

from __future__ import annotations

from collections.abc import Callable

from agent_connector_sdk.auth.client_credentials import ClientCredentialsAuth
from agent_connector_sdk.auth.oidc import (
    ClientCredentialsConfig,
    client_credentials_auth,
)
from agent_connector_sdk.auth.tokens import TokenRequestError
from agent_connector_sdk.credentials.references import SecretReferenceError
from agent_connector_sdk.credentials.resolution import resolve_secret_reference
from agent_connector_sdk.credentials.resolver import (
    CredentialResolver,
    CredentialUnavailableError,
)
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.descriptors import ConnectorDescriptor
from agent_connector_sdk.runner.errors import CredentialResolutionError

__all__ = ["CredentialEndpoints", "EndpointFactory"]

#: Builds the endpoint for a descriptor; may block (credential reads).
EndpointFactory = Callable[[ConnectorDescriptor], TransportEndpoint]


class CredentialEndpoints:
    """The default endpoint factory: every reference resolves or nothing opens.

    A client-credentials endpoint keeps one token cache per connector across
    cycles, so a cycle reuses a fresh token and mints only near expiry.
    """

    def __init__(self, resolver: CredentialResolver) -> None:
        self._resolver = resolver
        self._auth: dict[
            str, tuple[ClientCredentialsConfig, ClientCredentialsAuth]
        ] = {}

    def _client_credentials(
        self, descriptor: ConnectorDescriptor
    ) -> ClientCredentialsAuth | None:
        config = descriptor.endpoint.client_credentials
        if config is None:
            return None
        cached = self._auth.get(descriptor.connector)
        if cached is None or cached[0] != config:
            auth = client_credentials_auth(config, resolver=self._resolver)
            cached = self._auth[descriptor.connector] = (config, auth)
        cached[1].provider.get_token()
        return cached[1]

    def _auth_for(
        self, descriptor: ConnectorDescriptor
    ) -> ClientCredentialsAuth | None:
        try:
            return self._client_credentials(descriptor)
        except TokenRequestError as exc:
            raise CredentialResolutionError(
                f"connector {descriptor.connector!r} could not obtain a "
                "client-credentials token"
            ) from exc

    def __call__(self, descriptor: ConnectorDescriptor) -> TransportEndpoint:
        """Resolve the endpoint's references and build the endpoint.

        Raises:
            CredentialResolutionError: a reference is malformed or unavailable,
                or no client-credentials token could be obtained. The message
                names the connector, never the reference or the token.
        """
        spec = descriptor.endpoint
        try:
            env = {
                name: resolve_secret_reference(reference, self._resolver)
                for name, reference in spec.env.items()
            }
            token = (
                resolve_secret_reference(spec.bearer_token, self._resolver)
                if spec.bearer_token
                else ""
            )
        except (SecretReferenceError, CredentialUnavailableError) as exc:
            raise CredentialResolutionError(
                f"connector {descriptor.connector!r} has a credential reference "
                "that could not be resolved"
            ) from exc
        auth = self._auth_for(descriptor)
        return TransportEndpoint(
            url=spec.url,
            command=spec.command,
            args=spec.args,
            env=env,
            bearer_token=token,
            auth=auth,
            timeout_seconds=spec.timeout_seconds,
        )
