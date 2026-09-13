"""The collaborators every connector worker shares."""

from __future__ import annotations

from dataclasses import dataclass

from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.checkpoint_store import CheckpointStore
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.ports.transport import Transport
from agent_connector_sdk.runner.descriptors import RunnerSettings
from agent_connector_sdk.runner.endpoints import EndpointFactory
from agent_connector_sdk.runner.health_state import RunnerHealth

__all__ = ["RunnerServices"]


@dataclass(frozen=True)
class RunnerServices:
    """Ports and settings, composed once at the composition root."""

    transport: Transport
    sink: Sink
    store: CheckpointStore
    kinds: tuple[ArtifactKind, ...]
    endpoints: EndpointFactory
    settings: RunnerSettings
    #: Liveness/readiness state; ``None`` only in tests that build services
    #: directly without exercising the health surface.
    health: RunnerHealth | None = None
