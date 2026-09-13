"""Agreement checks for a connector manifest, presets and tool pins."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_connector_sdk.manifest.model import ConnectorManifest, SyncSpec
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.manifest.tool_schema import (
    COMPATIBILITY_FINGERPRINT_ALGORITHM,
    compatibility_fingerprint,
    legacy_empty_schema_fingerprint,
)

MANIFEST_FILE_NAME = "connector_manifest.yml"
PRESETS_FILE_NAME = "mcp_source_presets.json"
FINGERPRINTS_FILE_NAME = "tool_schema_fingerprints.json"

_PRESET_FIELDS_MIRRORED_IN_SYNC = (
    "server",
    "tool",
    "records_path",
    "id_field",
    "title_field",
    "text_field",
    "updated_field",
    "pagination",
    "doc_type",
)


@dataclass(frozen=True)
class ToolSchemaFingerprints:
    """The contents of ``tool_schema_fingerprints.json``."""

    connector: str
    algorithm: str
    tools: dict[str, str]


def _pin_mismatch(
    entry: SyncSpec, pinned: str | None, allow_pin_migration: bool
) -> bool:
    return not allow_pin_migration and (
        not entry.tool_schema_sha256 or entry.tool_schema_sha256 != pinned
    )


def _sync_violations(
    entry: SyncSpec,
    presets: dict[str, ToolPreset],
    tools: dict[str, str],
    *,
    allow_pin_migration: bool,
) -> list[str]:
    preset = presets.get(entry.preset)
    if preset is None:
        return [f"sync preset {entry.preset!r} is not declared in {PRESETS_FILE_NAME}"]
    violations: list[str] = []
    for field_name in _PRESET_FIELDS_MIRRORED_IN_SYNC:
        declared = getattr(entry, field_name)
        if declared is not None and declared != getattr(preset, field_name):
            violations.append(
                f"sync preset {entry.preset!r} field {field_name!r} differs from "
                f"{PRESETS_FILE_NAME}"
            )
    if (entry.action or "") != preset.action:
        violations.append(
            f"sync preset {entry.preset!r} field 'action' differs from "
            f"{PRESETS_FILE_NAME}"
        )
    if _pin_mismatch(entry, tools.get(preset.tool), allow_pin_migration):
        violations.append(
            f"sync preset {entry.preset!r} tool_schema_sha256 does not match the "
            f"pinned fingerprint for tool {preset.tool!r}"
        )
    return violations


def _empty_pin_violations(fingerprints: ToolSchemaFingerprints) -> list[str]:
    return [
        f"{FINGERPRINTS_FILE_NAME} pins tool {tool!r} to the fingerprint of an "
        "empty input schema, which verifies no contract; re-certify it from the "
        "server's tools/list"
        for tool, pinned in sorted(fingerprints.tools.items())
        if pinned
        in {
            compatibility_fingerprint(tool, {}),
            legacy_empty_schema_fingerprint(tool),
        }
    ]


def _pin_policy_violations(
    fingerprints: ToolSchemaFingerprints, allow_pin_migration: bool
) -> list[str]:
    if allow_pin_migration:
        return []
    violations = _empty_pin_violations(fingerprints)
    if fingerprints.algorithm != COMPATIBILITY_FINGERPRINT_ALGORITHM:
        violations.insert(
            0,
            f"{FINGERPRINTS_FILE_NAME} algorithm is not "
            f"{COMPATIBILITY_FINGERPRINT_ALGORITHM}",
        )
    return violations


def _unknown_tool_violations(
    presets: dict[str, ToolPreset], fingerprints: ToolSchemaFingerprints
) -> list[str]:
    preset_tools = {preset.tool for preset in presets.values()}
    return [
        f"{FINGERPRINTS_FILE_NAME} names unknown tool {tool!r}"
        for tool in sorted(set(fingerprints.tools) - preset_tools)
    ]


def _malformed_pin_violations(
    manifest: ConnectorManifest, fingerprints: ToolSchemaFingerprints
) -> list[str]:
    locations = [
        (f"fingerprint tool {tool!r}", pin)
        for tool, pin in sorted(fingerprints.tools.items())
    ]
    locations.extend(
        (f"sync preset {entry.preset!r}", entry.tool_schema_sha256 or "")
        for entry in manifest.sync
    )
    return [
        f"{location} has a malformed tool_schema_sha256"
        for location, pin in locations
        if pin and re.fullmatch(r"[0-9A-Fa-f]{64}", pin) is None
    ]


def validate_connector_package(
    manifest: ConnectorManifest,
    presets: dict[str, ToolPreset],
    fingerprints: ToolSchemaFingerprints,
    *,
    allow_pin_migration: bool = False,
) -> list[str]:
    """Return every disagreement between manifest, presets and fingerprints.

    ``allow_pin_migration`` permits only absent, stale or legacy pin values so
    the certifier can repair them. Connector, preset and tool identities still
    have to agree.
    """
    violations = _malformed_pin_violations(manifest, fingerprints)
    violations.extend(_pin_policy_violations(fingerprints, allow_pin_migration))
    if fingerprints.connector != manifest.connector:
        violations.append(
            f"{FINGERPRINTS_FILE_NAME} connector does not match the manifest connector"
        )
    for entry in manifest.sync:
        violations.extend(
            _sync_violations(
                entry,
                presets,
                fingerprints.tools,
                allow_pin_migration=allow_pin_migration,
            )
        )
    declared = {entry.preset for entry in manifest.sync}
    violations.extend(
        f"preset {name!r} is not declared in the manifest sync section"
        for name in sorted(set(presets) - declared)
    )
    violations.extend(_unknown_tool_violations(presets, fingerprints))
    return violations
