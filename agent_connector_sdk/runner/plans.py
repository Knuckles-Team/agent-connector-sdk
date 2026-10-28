"""What a cycle does: load a connector's adapters and plan each cycle."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.discovery import ActivationPolicy
from agent_connector_sdk.ingest.live_declaration import RESOURCES_URI
from agent_connector_sdk.manifest.declaration import (
    ContractError,
    SyncContract,
    contract_from_document,
)
from agent_connector_sdk.manifest.model import SyncSpec
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.change_source import ChangeEvent
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.ports.source_adapter import SourceAdapter
from agent_connector_sdk.runner.descriptors import ConnectorDescriptor
from agent_connector_sdk.runner.errors import RunnerConfigurationError
from agent_connector_sdk.runner.event_adapters import (
    _build_event_adapters,
    _ordinary_names,
)

__all__ = [
    "CyclePlan",
    "change_plan",
    "full_plan",
    "load_sync_adapters",
]

_LIST_KINDS = frozenset({"tools", "prompts", "resources"})


@dataclass(frozen=True)
class CyclePlan:
    """Whether a cycle provisions content, and which presets it syncs."""

    provision: bool
    presets: frozenset[str]


def _raise_problems(descriptor: ConnectorDescriptor, problems: list[str]) -> None:
    if problems:
        raise RunnerConfigurationError(
            f"connector {descriptor.connector!r}: {'; '.join(problems)}"
        )


def _selection_problems(
    descriptor: ConnectorDescriptor, declared: Collection[str]
) -> list[str]:
    selected = descriptor.presets or tuple(declared)
    triggered = {name for names in descriptor.data_resources.values() for name in names}
    missing = [
        f"preset {name!r} is not declared" for name in selected if name not in declared
    ]
    unselected = [
        f"data resource preset {name!r} is not selected"
        for name in sorted(triggered - set(selected))
    ]
    return [*missing, *unselected]


def _mapping_reference_problems(
    descriptor: ConnectorDescriptor,
    manifest: SyncContract,
    selected_specs: Mapping[str, SyncSpec],
) -> list[str]:
    reference = descriptor.resolved_mapping_reference
    manifest_reference = f"connector:{descriptor.connector}"
    if reference == manifest_reference:
        return _whole_declaration_mapping_problems(manifest, selected_specs)
    return _explicit_mapping_problems(reference, manifest_reference, manifest)


def _whole_declaration_mapping_problems(
    manifest: SyncContract, selected_specs: Mapping[str, SyncSpec]
) -> list[str]:
    if len(manifest.schema_mappings) == 1:
        return []
    presets = (
        ToolPreset.from_mapping(name, dict(spec.raw))
        for name, spec in selected_specs.items()
    )
    if all(
        preset.record_mode == "typed_entities"
        and bool(preset.node_type_field)
        and preset.strict_schema
        for preset in presets
    ):
        return []
    return [
        "a whole-declaration mapping reference with multiple mappings requires "
        "strict typed_entities presets"
    ]


def _explicit_mapping_problems(
    reference: str, manifest_reference: str, manifest: SyncContract
) -> list[str]:
    prefix = f"{manifest_reference}#mappings/"
    if not reference.startswith(prefix):
        return ["a mapping reference must name this connector's exact declared mapping"]
    key = reference.removeprefix(prefix)
    return (
        []
        if key and key in manifest.schema_mappings
        else [f"mapping reference {reference!r} does not name a declared mapping"]
    )


async def load_sync_adapters(
    descriptor: ConnectorDescriptor,
    session: McpSession,
    *,
    policy: ActivationPolicy | None = None,
) -> dict[str, SourceAdapter]:
    """Build the adapters from the server's own ``connector://resources``.

    The MCP server is the only place connector metadata is read from; tool
    fingerprints are taken from the handshake.

    Raises:
        RunnerConfigurationError: the server declares no sync preset, or its
            declaration is invalid or names another connector.
    """
    try:
        contract = contract_from_document(await session.read_resource(RESOURCES_URI))
    except ContractError as exc:
        raise RunnerConfigurationError(
            f"connector {descriptor.connector!r}: {exc}"
        ) from exc
    if contract is None:
        raise RunnerConfigurationError(
            f"connector {descriptor.connector!r}: the server declares no sync "
            "preset (source_meta(preset=...) on a read tool)"
        )
    if contract.connector != descriptor.connector:
        _raise_problems(
            descriptor, [f"the server declares connector {contract.connector!r}"]
        )
    adapters = _build_sync_adapters(descriptor, contract)
    events = await _build_event_adapters(descriptor, session, contract, policy=policy)
    adapters.update(events)
    return adapters


def _build_sync_adapters(
    descriptor: ConnectorDescriptor, manifest: SyncContract
) -> dict[str, SourceAdapter]:
    specs = {spec.preset: spec for spec in manifest.sync}
    selected = descriptor.presets or tuple(specs)
    _raise_problems(
        descriptor,
        [
            *_selection_problems(descriptor, specs),
            *_mapping_reference_problems(
                descriptor,
                manifest,
                {name: specs[name] for name in selected if name in specs},
            ),
        ],
    )
    return {
        name: McpToolSourceAdapter.from_sync_spec(
            specs[name],
            connector=manifest.connector,
            mapping_reference=descriptor.resolved_mapping_reference,
            schema_mappings=manifest.schema_mappings,
            resources=manifest.resources,
            parents=specs,
        )
        for name in _ordinary_names(selected, specs)
    }


def full_plan(descriptor: ConnectorDescriptor, presets: Iterable[str]) -> CyclePlan:
    """Provision (when enabled) and sync every preset: the first and scheduled cycles."""
    return CyclePlan(descriptor.provision, frozenset(presets))


def change_plan(
    descriptor: ConnectorDescriptor,
    changes: Iterable[ChangeEvent],
    resource_uris: frozenset[str],
) -> CyclePlan:
    """React to change events.

    A list change, or an update of a resource that is part of the pack
    (``resource_uris``), re-provisions; an update of a mapped data resource
    syncs its presets.
    """
    events = tuple(changes)
    mapping: Mapping[str, tuple[str, ...]] = descriptor.data_resources
    provision = descriptor.provision and any(
        event.kind in _LIST_KINDS or event.uri in resource_uris for event in events
    )
    presets = frozenset(
        name
        for event in events
        if event.kind == "resource"
        for name in mapping.get(event.uri, ())
    )
    return CyclePlan(provision, presets)
