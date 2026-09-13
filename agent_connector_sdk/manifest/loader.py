"""Load a connector's declarative package files and check they agree.

A connector package declares its sync contract three times, by design: the
presets (``mcp_source_presets.json``), the pinned tool fingerprints
(``tool_schema_fingerprints.json``) and the generated manifest
(``connector_manifest.yml``). :func:`validate_connector_package` fails closed
when those three disagree. Signature verification of release bundles is not
part of this module; it belongs to the release tooling that signs them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from agent_connector_sdk.manifest.model import ConnectorManifest, SyncSpec
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.manifest.tool_schema import (
    COMPATIBILITY_FINGERPRINT_ALGORITHM,
    compatibility_fingerprint,
    legacy_empty_schema_fingerprint,
)

__all__ = [
    "FINGERPRINTS_FILE_NAME",
    "MANIFEST_FILE_NAME",
    "PRESETS_FILE_NAME",
    "ManifestError",
    "ToolSchemaFingerprints",
    "load_manifest",
    "load_tool_presets",
    "load_tool_schema_fingerprints",
    "require_valid_connector_package",
    "validate_connector_package",
]

MANIFEST_FILE_NAME = "connector_manifest.yml"
PRESETS_FILE_NAME = "mcp_source_presets.json"
FINGERPRINTS_FILE_NAME = "tool_schema_fingerprints.json"

_MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
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


class ManifestError(ValueError):
    """A connector package file is unreadable, malformed or inconsistent."""


@dataclass(frozen=True)
class ToolSchemaFingerprints:
    """The contents of ``tool_schema_fingerprints.json``."""

    connector: str
    algorithm: str
    tools: dict[str, str]


def _read_bounded(path: Path) -> bytes:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ManifestError(f"{path.name} is unreadable") from exc
    if len(payload) > _MAX_DOCUMENT_BYTES:
        raise ManifestError(f"{path.name} is too large")
    return payload


def load_manifest(path: Path) -> ConnectorManifest:
    """Parse and validate ``connector_manifest.yml``."""
    try:
        document = yaml.safe_load(_read_bounded(path))
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path.name} is not valid YAML") from exc
    try:
        return ConnectorManifest.model_validate(document)
    except ValidationError as exc:
        raise ManifestError(f"{path.name} does not match the manifest schema") from exc


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(_read_bounded(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"{path.name} is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ManifestError(f"{path.name} must be a JSON object")
    return document


def load_tool_presets(path: Path) -> dict[str, ToolPreset]:
    """Parse ``mcp_source_presets.json``; keys starting with ``_`` are comments."""
    presets: dict[str, ToolPreset] = {}
    for name, raw in _load_json_object(path).items():
        if name.startswith("_"):
            continue
        if not isinstance(raw, dict):
            raise ManifestError(f"preset {name!r} must be a JSON object")
        try:
            presets[name] = ToolPreset.from_mapping(name, raw)
        except ValidationError as exc:
            raise _invalid_preset(name, exc) from exc
    return presets


def load_tool_schema_fingerprints(path: Path) -> ToolSchemaFingerprints:
    """Parse ``tool_schema_fingerprints.json``."""
    document = _load_json_object(path)
    tools = document.get("tools")
    if not isinstance(tools, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in tools.items()
    ):
        raise ManifestError(f"{path.name} must map tool names to fingerprints")
    return ToolSchemaFingerprints(
        connector=str(document.get("connector") or ""),
        algorithm=str(document.get("algorithm") or ""),
        tools=dict(tools),
    )


def _sync_violations(
    entry: SyncSpec, presets: dict[str, ToolPreset], tools: dict[str, str]
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
            f"sync preset {entry.preset!r} field 'action' differs from {PRESETS_FILE_NAME}"
        )
    pinned = tools.get(preset.tool)
    if not entry.tool_schema_sha256 or entry.tool_schema_sha256 != pinned:
        violations.append(
            f"sync preset {entry.preset!r} tool_schema_sha256 does not match the "
            f"pinned fingerprint for tool {preset.tool!r}"
        )
    return violations


def validate_connector_package(
    manifest: ConnectorManifest,
    presets: dict[str, ToolPreset],
    fingerprints: ToolSchemaFingerprints,
) -> list[str]:
    """Return every disagreement between manifest, presets and fingerprints."""
    violations: list[str] = []
    if fingerprints.algorithm != COMPATIBILITY_FINGERPRINT_ALGORITHM:
        violations.append(
            f"{FINGERPRINTS_FILE_NAME} algorithm is not "
            f"{COMPATIBILITY_FINGERPRINT_ALGORITHM}"
        )
    if fingerprints.connector != manifest.connector:
        violations.append(
            f"{FINGERPRINTS_FILE_NAME} connector does not match the manifest connector"
        )
    violations.extend(_empty_pin_violations(fingerprints))
    for entry in manifest.sync:
        violations.extend(_sync_violations(entry, presets, fingerprints.tools))
    declared = {entry.preset for entry in manifest.sync}
    violations.extend(
        f"preset {name!r} is not declared in the manifest sync section"
        for name in sorted(set(presets) - declared)
    )
    return violations


def _invalid_preset(name: str, exc: ValidationError) -> ManifestError:
    reasons = "; ".join(
        str(error["msg"]).removeprefix("Value error, ") for error in exc.errors()
    )
    return ManifestError(f"preset {name!r} is invalid: {reasons}")


def _empty_pin_violations(fingerprints: ToolSchemaFingerprints) -> list[str]:
    """Pins equal to the fingerprint of an empty input schema verify nothing."""
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


def require_valid_connector_package(package_root: Path) -> ConnectorManifest:
    """Load a connector package's three files and raise on any disagreement.

    ``package_root`` holds ``connector_manifest.yml``; the presets and
    fingerprints are read from its ``connectors/`` directory, the fleet layout.
    """
    manifest = load_manifest(package_root / MANIFEST_FILE_NAME)
    connectors = package_root / "connectors"
    violations = validate_connector_package(
        manifest,
        load_tool_presets(connectors / PRESETS_FILE_NAME),
        load_tool_schema_fingerprints(connectors / FINGERPRINTS_FILE_NAME),
    )
    if violations:
        raise ManifestError("; ".join(violations))
    return manifest
