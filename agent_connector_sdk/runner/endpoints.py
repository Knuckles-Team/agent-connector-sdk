"""Build transport endpoints from descriptors, resolving credentials first."""

from __future__ import annotations

from collections.abc import Callable

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
    """The default endpoint factory: every reference resolves or nothing opens."""

    def __init__(self, resolver: CredentialResolver) -> None:
        self._resolver = resolver

    def __call__(self, descriptor: ConnectorDescriptor) -> TransportEndpoint:
        """Resolve the endpoint's references and build the endpoint.

        Raises:
            CredentialResolutionError: a reference is malformed or unavailable.
                The message names the connector, never the reference.
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
        return TransportEndpoint(
            url=spec.url,
            command=spec.command,
            args=spec.args,
            env=env,
            bearer_token=token,
            timeout_seconds=spec.timeout_seconds,
        )
