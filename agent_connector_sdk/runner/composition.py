"""The runner's composition root: load certified extensions and build services."""

from __future__ import annotations

import logging
from pathlib import Path

from agent_connector_sdk import decide
from agent_connector_sdk.credentials.resolution import default_credential_resolver
from agent_connector_sdk.decide.epistemic_graph import EpistemicGraphDecisionRunner
from agent_connector_sdk.decide.points import Bindings
from agent_connector_sdk.decide.transport import GeneratedTransport
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
from agent_connector_sdk.ports.decide_runner import DecisionRunner
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.ports.transport import Transport
from agent_connector_sdk.runner.descriptors import RunnerSettings
from agent_connector_sdk.runner.endpoints import CredentialEndpoints
from agent_connector_sdk.runner.health_state import RunnerHealth
from agent_connector_sdk.runner.services import RunnerServices
from agent_connector_sdk.sinks.epistemic_graph import PackImportAuthorityResolver

__all__ = ["default_services", "extension_instance"]

_logger = logging.getLogger(__name__)

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


def _decide_runner(
    sink_name: str,
    sink_client: object | None,
    *,
    decide_tenant: str | None,
    decide_bindings: Bindings | None,
) -> DecisionRunner | None:
    """The EG-backed connector decision runner, when this process has both a
    verified EG session and a tenant to decide as.

    ``sink_client`` alone is not enough: a real ``Decide`` request is
    tenant-scoped, and this composition root never invents one (the same
    "never discovers... at this boundary" rule ``default_services`` already
    documents). With no ``decide_tenant`` -- true for every caller today --
    no runner is built and every connector-side ``Decide`` call site stays
    exactly its deterministic fallback, unchanged. ``decide_bindings``
    defaults to :data:`agent_connector_sdk.decide.points.EMPTY_BINDINGS`:
    bound or not, the runner installs the same way, and an unbound point
    still never reaches EG.

    The transport is built with no engine loop (``loop=None``): this
    function runs before the connector's own ``anyio``/``asyncio`` loop
    starts, so there is no other-thread loop reference to bind yet. A sync
    call site (:func:`agent_connector_sdk.decide.choose`) safely falls back
    with reason ``unavailable`` until a future change threads one through;
    an async call site (:func:`agent_connector_sdk.decide.achoose`) already
    works, since it needs no thread bridging.

    Logs once, at ``WARNING``, when a verified EG client exists but no
    tenant does -- the one case worth an operator's attention (a client
    without connector decisions configured is unremarkable; a client with no
    tenant to decide as is a configuration gap). Never invents a tenant.
    """
    if sink_name != "epistemic_graph" or sink_client is None:
        return None
    if decide_tenant is None:
        _logger.warning(
            "epistemic_graph sink has a verified client but no decide_tenant "
            "(no RUNNER_DECIDE_TENANT override and none was derived from the "
            "verified session) -- connector-side decisions stay their "
            "deterministic fallback; not installing a decision runner"
        )
        return None
    transport = GeneratedTransport(client=sink_client)
    if decide_bindings is None:
        return EpistemicGraphDecisionRunner(transport=transport, tenant=decide_tenant)
    return EpistemicGraphDecisionRunner(
        transport=transport, tenant=decide_tenant, bindings=decide_bindings
    )


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
    decide_tenant: str | None = None,
    decide_bindings: Bindings | None = None,
) -> RunnerServices:
    """Services from certified entry points and credential resolution.

    Every artifact kind declared in ``agent_connector_sdk.artifact_kinds`` is
    provisioned. An epistemic-graph deployment must inject the already verified
    generated client. The SDK never discovers an engine endpoint, reads a token,
    or mints request identity at this boundary.

    With ``decide_tenant`` also given, the EG-backed connector decision
    runner (:class:`~agent_connector_sdk.decide.epistemic_graph.EpistemicGraphDecisionRunner`)
    is built over the SAME verified ``sink_client`` and installed process-wide
    (:func:`agent_connector_sdk.decide.install_runner`) -- one composition
    root, one EG session, both consumers. ``decide_tenant`` is the caller's
    own verified session tenant, the same one it authenticated ``sink_client``
    as -- this function never derives or invents one from ``sink_client``
    itself (an intentionally opaque ``object`` at this boundary). The
    ``RUNNER_DECIDE_TENANT`` environment variable, read by
    :func:`agent_connector_sdk.runner.cli.main`'s entrypoint (never here --
    see that module's own env-reading convention), overrides it, matching
    ``config.py``'s "an explicit environment variable always wins" rule. With
    neither (every caller before this override existed), no runner is
    installed and every connector-side ``Decide`` call site stays exactly its
    deterministic fallback -- logged once, at ``WARNING``, only when a
    verified client exists with no tenant to pair it with.

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
    runner = _decide_runner(
        sink_name,
        sink_client,
        decide_tenant=decide_tenant,
        decide_bindings=decide_bindings,
    )
    if runner is not None:
        decide.install_runner(runner)
    return RunnerServices(
        transport=transport,
        sink=sink,
        kinds=kinds,
        endpoints=CredentialEndpoints(default_credential_resolver()),
        settings=settings,
        health=RunnerHealth(sink=sink, liveness_window_seconds=window),
        decide_runner=runner,
    )
