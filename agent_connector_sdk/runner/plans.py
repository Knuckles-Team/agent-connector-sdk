"""What a cycle does: load a connector's adapters and plan each cycle."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.manifest.loader import (
    FINGERPRINTS_FILE_NAME,
    MANIFEST_FILE_NAME,
    PRESETS_FILE_NAME,
    ManifestError,
    load_manifest,
    load_tool_presets,
    load_tool_schema_fingerprints,
    validate_connector_package,
)
from agent_connector_sdk.manifest.model import ConnectorManifest, SyncSpec
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.change_source import ChangeEvent
from agent_connector_sdk.runner.descriptors import ConnectorDescriptor
from agent_connector_sdk.runner.errors import RunnerConfigurationError

__all__ = ["CyclePlan", "change_plan", "full_plan", "load_sync_adapters"]

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


def _validated_manifest(descriptor: ConnectorDescriptor) -> ConnectorManifest:
    connectors = descriptor.resolved_connectors_dir
    try:
        manifest = load_manifest(descriptor.package_root / MANIFEST_FILE_NAME)
        violations = validate_connector_package(
            manifest,
            load_tool_presets(connectors / PRESETS_FILE_NAME),
            load_tool_schema_fingerprints(connectors / FINGERPRINTS_FILE_NAME),
        )
    except ManifestError as exc:
        raise RunnerConfigurationError(
            f"connector {descriptor.connector!r}: {exc}"
        ) from exc
    if manifest.connector != descriptor.connector:
        violations.append(f"the package is connector {manifest.connector!r}")
    _raise_problems(descriptor, violations)
    return manifest


def _selection_problems(
    descriptor: ConnectorDescriptor, declared: Collection[str]
) -> list[str]:
    selected = descriptor.presets or tuple(declared)
    triggered = {name for names in descriptor.data_resources.values() for name in names}
    missing = [
        f"preset {name!r} is not in the manifest"
        for name in selected
        if name not in declared
    ]
    unselected = [
        f"data resource preset {name!r} is not selected"
        for name in sorted(triggered - set(selected))
    ]
    return [*missing, *unselected]


def _mapping_reference_problems(
    descriptor: ConnectorDescriptor,
    manifest: ConnectorManifest,
    selected_specs: Mapping[str, SyncSpec],
) -> list[str]:
    reference = descriptor.resolved_mapping_reference
    manifest_reference = f"manifest:{descriptor.connector}"
    if reference == manifest_reference:
        return _whole_manifest_mapping_problems(manifest, selected_specs)
    return _explicit_mapping_problems(reference, manifest_reference, manifest)


def _whole_manifest_mapping_problems(
    manifest: ConnectorManifest, selected_specs: Mapping[str, SyncSpec]
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
        "a whole-manifest mapping reference with multiple mappings requires "
        "strict typed_entities presets"
    ]


def _explicit_mapping_problems(
    reference: str, manifest_reference: str, manifest: ConnectorManifest
) -> list[str]:
    prefix = f"{manifest_reference}#schema_mappings/"
    if not reference.startswith(prefix):
        return ["a mapping reference must name this connector's exact manifest mapping"]
    key = reference.removeprefix(prefix)
    return (
        []
        if key and key in manifest.schema_mappings
        else [f"mapping reference {reference!r} does not name a manifest mapping"]
    )


def load_sync_adapters(
    descriptor: ConnectorDescriptor,
) -> dict[str, McpToolSourceAdapter]:
    """Validate the connector package and build an adapter per selected preset.

    Raises:
        RunnerConfigurationError: the package is invalid (manifest, presets and
            pinned fingerprints disagree), belongs to another connector, or the
            descriptor names presets it does not declare.
    """
    manifest = _validated_manifest(descriptor)
    return _build_sync_adapters(descriptor, manifest)


def _build_sync_adapters(
    descriptor: ConnectorDescriptor, manifest: ConnectorManifest
) -> dict[str, McpToolSourceAdapter]:
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
        )
        for name in selected
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
