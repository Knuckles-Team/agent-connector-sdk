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
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from agent_connector_sdk.manifest.model import ConnectorManifest
from agent_connector_sdk.manifest.package_validation import (
    FINGERPRINTS_FILE_NAME,
    MANIFEST_FILE_NAME,
    PRESETS_FILE_NAME,
    ToolSchemaFingerprints,
    validate_connector_package,
)
from agent_connector_sdk.manifest.presets import ToolPreset

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

_MAX_DOCUMENT_BYTES = 4 * 1024 * 1024


class ManifestError(ValueError):
    """A connector package file is unreadable, malformed or inconsistent."""


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


def _invalid_preset(name: str, exc: ValidationError) -> ManifestError:
    reasons = "; ".join(
        str(error["msg"]).removeprefix("Value error, ") for error in exc.errors()
    )
    return ManifestError(f"preset {name!r} is invalid: {reasons}")


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
