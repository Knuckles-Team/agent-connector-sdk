"""The ``ConnectorRegistry`` port: which connectors the runner serves.

A static configuration file implements it today
(:class:`~agent_connector_sdk.runner.static_registry.StaticConfigRegistry`).
epistemic-graph's server registry, where connector servers self-register with a
lease, implements the same port once it is published (RF-ADR-009 W1); the
runner re-reads the registry periodically, so a new or changed registration
starts or restarts that connector's worker.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.runner.descriptors import ConnectorDescriptor

__all__ = ["ConnectorRegistry"]


@runtime_checkable
class ConnectorRegistry(Protocol):
    """Lists the connectors to serve."""

    async def connectors(self) -> tuple[ConnectorDescriptor, ...]:
        """Every connector descriptor currently registered.

        Raises:
            RunnerConfigurationError: the registry cannot be read or is invalid.
        """
        ...
