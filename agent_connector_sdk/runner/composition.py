"""The runner's composition root: load certified extensions and build services."""

from __future__ import annotations

from pathlib import Path

from agent_connector_sdk.credentials.resolution import default_credential_resolver
from agent_connector_sdk.discovery import (
    ARTIFACT_KIND_GROUP,
    SINK_GROUP,
    TRANSPORT_GROUP,
    ActivationPolicy,
    ExtensionDiscoveryError,
    discover_extensions,
    load_extension,
    sdk_reference_extensions,
)
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.ports.transport import Transport
from agent_connector_sdk.runner.descriptors import RunnerSettings
from agent_connector_sdk.runner.endpoints import CredentialEndpoints
from agent_connector_sdk.runner.health_state import RunnerHealth
from agent_connector_sdk.runner.services import RunnerServices
from agent_connector_sdk.sinks.epistemic_graph import PackImportAuthorityResolver

__all__ = ["default_services", "extension_instance"]

#: Minimum liveness window regardless of a very short registry-refresh
#: setting, so a slow-but-healthy loop iteration is never mistaken for a wedge.
_MIN_LIVENESS_WINDOW_SECONDS = 30.0


def extension_instance(
    group: str, name: str, *, policy: ActivationPolicy, **arguments: object
) -> object:
    """Load a certified extension and construct it with ``arguments``.

    Raises:
        ExtensionDiscoveryError: the entry point does not name a constructor.
    """
    target = load_extension(group, name, policy=policy)
    if not callable(target):
        raise ExtensionDiscoveryError(
            f"extension {name!r} in {group} is not constructible"
        )
    return target(**arguments)


def _sink_arguments(
    sink_name: str,
    sink_client: object | None,
    pack_import_authority: PackImportAuthorityResolver | None,
) -> dict[str, object]:
    supplied = sink_client is not None or pack_import_authority is not None
    if sink_name != "epistemic_graph":
        if supplied:
            raise ExtensionDiscoveryError(
                "sink_client and pack_import_authority apply only to the "
                "epistemic_graph sink"
            )
        return {}
    if sink_client is None or pack_import_authority is None:
        raise ExtensionDiscoveryError(
            "the epistemic_graph sink requires an injected verified client "
            "and pack import authority resolver"
        )
    return {
        "client": sink_client,
        "pack_import_authority": pack_import_authority,
    }


def _artifact_kinds(policy: ActivationPolicy) -> tuple[ArtifactKind, ...]:
    kinds = tuple(
        extension_instance(ARTIFACT_KIND_GROUP, identity.name, policy=policy)
        for identity in discover_extensions(ARTIFACT_KIND_GROUP)
    )
    checked = tuple(kind for kind in kinds if isinstance(kind, ArtifactKind))
    if len(checked) != len(kinds):
        raise ExtensionDiscoveryError("an artifact kind extension has the wrong port")
    return checked


def default_services(
    settings: RunnerSettings,
    *,
    state_dir: Path,
    sink_name: str,
    sink_client: object | None = None,
    pack_import_authority: PackImportAuthorityResolver | None = None,
    policy: ActivationPolicy | None = None,
) -> RunnerServices:
    """Services from certified entry points and credential resolution.

    Every artifact kind declared in ``agent_connector_sdk.artifact_kinds`` is
    provisioned. An epistemic-graph deployment must inject the already verified
    generated client. The SDK never discovers an engine endpoint, reads a token,
    or mints request identity at this boundary.

    Raises:
        ExtensionActivationError: an extension is not certified by ``policy``.
        ExtensionDiscoveryError: an extension is missing or of the wrong port.
    """
    del state_dir  # Stable composition parameter; EG owns all durable checkpoints.
    chosen = policy or sdk_reference_extensions()
    transport = extension_instance(TRANSPORT_GROUP, "mcp", policy=chosen)
    sink = extension_instance(
        SINK_GROUP,
        sink_name,
        policy=chosen,
        **_sink_arguments(sink_name, sink_client, pack_import_authority),
    )
    kinds = _artifact_kinds(chosen)
    if not isinstance(transport, Transport) or not isinstance(sink, Sink):
        raise ExtensionDiscoveryError("transport or sink extension has the wrong port")
    window = max(3 * settings.registry_refresh_seconds, _MIN_LIVENESS_WINDOW_SECONDS)
    return RunnerServices(
        transport=transport,
        sink=sink,
        kinds=kinds,
        endpoints=CredentialEndpoints(default_credential_resolver()),
        settings=settings,
        health=RunnerHealth(sink=sink, liveness_window_seconds=window),
    )
