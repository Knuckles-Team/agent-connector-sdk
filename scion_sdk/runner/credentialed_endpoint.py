"""Resolve one connector's endpoint, recording the outcome for health."""

from __future__ import annotations

import anyio

from scion_sdk.ports.session import TransportEndpoint
from scion_sdk.runner.descriptors import ConnectorDescriptor
from scion_sdk.runner.errors import CredentialResolutionError
from scion_sdk.runner.health_reporting import note_credentials
from scion_sdk.runner.services import RunnerServices

__all__ = ["resolve_endpoint"]


async def resolve_endpoint(
    services: RunnerServices, descriptor: ConnectorDescriptor
) -> TransportEndpoint:
    """Resolve ``descriptor``'s endpoint; record success or failure.

    Raises:
        CredentialResolutionError: a reference is malformed or unavailable.
    """
    name = descriptor.connector
    try:
        endpoint = await anyio.to_thread.run_sync(services.endpoints, descriptor)
    except CredentialResolutionError as exc:
        note_credentials(services.health, name, ok=False, error=str(exc))
        raise
    note_credentials(services.health, name, ok=True)
    return endpoint
