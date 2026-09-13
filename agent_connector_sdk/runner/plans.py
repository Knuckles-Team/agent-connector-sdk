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
from agent_connector_sdk.manifest.model import ConnectorManifest
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
    specs = {spec.preset: spec for spec in manifest.sync}
    _raise_problems(descriptor, _selection_problems(descriptor, specs))
    return {
        name: McpToolSourceAdapter.from_sync_spec(
            specs[name], connector=manifest.connector
        )
        for name in descriptor.presets or specs
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
