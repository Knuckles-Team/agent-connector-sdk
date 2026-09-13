"""Manifest schema, presets, fingerprints, live contract and the package validator."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent_connector_sdk.manifest.live_contract import (
    LiveToolContract,
    validate_live_tool_contract,
)
from agent_connector_sdk.manifest.loader import (
    FINGERPRINTS_FILE_NAME,
    MANIFEST_FILE_NAME,
    PRESETS_FILE_NAME,
    ManifestError,
    ToolSchemaFingerprints,
    load_manifest,
    load_tool_presets,
    load_tool_schema_fingerprints,
    require_valid_connector_package,
    validate_connector_package,
)
from agent_connector_sdk.manifest.model import (
    ActionParameterSpec,
    ActionSpec,
    ConnectorManifest,
    EventSpec,
    IdentitySpec,
    IntegrityInfo,
    PermissionsSpec,
    PolicySpec,
    ProvenanceSpec,
    ResourceRelation,
    ResourceSpec,
    SchemaMapping,
    SyncSpec,
)
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.manifest.tool_schema import (
    COMPATIBILITY_FINGERPRINT_ALGORITHM,
    ToolSchemaContractError,
    canonical_input_schema,
    canonical_output_schema,
    compatibility_fingerprint,
    read_field,
    schema_fingerprint,
)

SCHEMA = {
    "type": "object",
    "description": "presentation only",
    "properties": {
        "action": {"type": "string", "default": "x", "enum": ["read", "list"]},
        "params_json": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["params_json", "action"],
}


def _manifest(**overrides: object) -> ConnectorManifest:
    base: dict[str, object] = {
        "connector": "demo-agent",
        "resources": [
            ResourceSpec(
                name="Item", relations=[ResourceRelation(name="in", target="Item")]
            )
        ],
        "actions": [ActionSpec(id="read", parameters=[ActionParameterSpec(name="q")])],
        "events": [EventSpec(name="demo.updated")],
        "identity": IdentitySpec(id_field={"item": "id"}),
        "permissions": PermissionsSpec(read_roles=["reader"]),
        "schema_mappings": {"Item": SchemaMapping(ontology_class="Document")},
        "policy": PolicySpec(rls=[]),
        "provenance": ProvenanceSpec(integrity=IntegrityInfo(hash="h")),
    }
    base.update(overrides)
    return ConnectorManifest.model_validate(base)


def test_manifest_model_invariants() -> None:
    manifest = _manifest()
    assert manifest.resolved_ontology_source == "demo-agent"
    with pytest.raises(ValidationError, match="target_resource"):
        _manifest(actions=[ActionSpec(id="write", target_resource="Missing")])
    with pytest.raises(ValidationError, match="destructive"):
        _manifest(actions=[ActionSpec(id="delete_item", requires_approval=False)])


def test_fixture_package_loads(package_root: Path) -> None:
    manifest = require_valid_connector_package(package_root)
    assert manifest.connector == "demo-agent"
    assert isinstance(manifest.sync[0], SyncSpec)
    assert (package_root / MANIFEST_FILE_NAME).is_file()
    presets = load_tool_presets(package_root / "connectors" / PRESETS_FILE_NAME)
    assert presets["demo"].mapping_hints == {"type_field": "kind"}
    fingerprints = load_tool_schema_fingerprints(
        package_root / "connectors" / FINGERPRINTS_FILE_NAME
    )
    assert isinstance(fingerprints, ToolSchemaFingerprints)
    assert fingerprints.algorithm == COMPATIBILITY_FINGERPRINT_ALGORITHM


def test_validator_reports_every_disagreement(package_root: Path) -> None:
    manifest = load_manifest(package_root / MANIFEST_FILE_NAME)
    presets = load_tool_presets(package_root / "connectors" / PRESETS_FILE_NAME)
    presets["extra"] = presets["demo"].model_copy(update={"name": "extra"})
    wrong = ToolSchemaFingerprints(
        connector="other", algorithm="v0", tools={"demo_reader": "0"}
    )
    violations = validate_connector_package(manifest, presets, wrong)
    assert len(violations) == 4
    assert any("extra" in violation for violation in violations)


def test_loader_rejects_bad_files(tmp_path: Path) -> None:
    (tmp_path / "manifest.yml").write_text("connector: [unclosed")
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "manifest.yml")
    (tmp_path / "presets.json").write_text(json.dumps({"broken": {"server": "s"}}))
    with pytest.raises(ManifestError):
        load_tool_presets(tmp_path / "presets.json")
    (tmp_path / "fingerprints.json").write_text(json.dumps({"tools": {"t": 1}}))
    with pytest.raises(ManifestError):
        load_tool_schema_fingerprints(tmp_path / "fingerprints.json")


def test_preset_pagination_needs_its_parameters() -> None:
    with pytest.raises(ValidationError):
        ToolPreset(name="p", server="s", tool="t", pagination="cursor")
    with pytest.raises(ValidationError):
        ToolPreset(name="p", server="s", tool="t", pagination="page")
    preset = ToolPreset.from_mapping(
        "p",
        {"server": "s", "tool": "t", "node_id_template": "{id}", "updated_field": None},
    )
    assert preset.mapping_hints == {"node_id_template": "{id}"}
    assert preset.updated_field == ""


def test_canonical_schema_and_fingerprints() -> None:
    tool = {
        "name": "reader",
        "inputSchema": SCHEMA,
        "outputSchema": {"type": "object"},
    }
    exact = canonical_input_schema(tool)
    compatible = canonical_input_schema(tool, include_presentation=False)
    assert exact["required"] == ["action", "params_json"]
    assert "default" not in exact["properties"]["action"]
    assert "description" in exact and "description" not in compatible
    assert canonical_output_schema(tool) == {"type": "object"}
    assert canonical_output_schema({"name": "no-output"}) is None
    assert schema_fingerprint("reader", exact) != compatibility_fingerprint(
        "reader", compatible
    )
    assert (
        read_field(
            SimpleNamespace(input_schema=SCHEMA),
            "inputSchema",
            attr_names=("input_schema",),
        )
        == SCHEMA
    )
    with pytest.raises(ToolSchemaContractError):
        canonical_input_schema({"name": "bad", "inputSchema": ["not", "an", "object"]})


def test_live_contract_validation() -> None:
    tool = {"name": "reader", "inputSchema": SCHEMA}
    pinned = compatibility_fingerprint(
        "reader", canonical_input_schema(tool, include_presentation=False)
    )
    contract = validate_live_tool_contract(
        {"tools": [tool]},
        tool_name="reader",
        expected_schema_sha256=pinned,
        required_argument_types={"action": "string", "params_json": "string"},
        required_argument_enums={"action": {"read"}},
    )
    assert isinstance(contract, LiveToolContract)
    assert contract.compatibility_sha256 == pinned
    for listing, pinned_sha, required in (
        ({"tools": []}, "", {}),
        ({"tools": [tool, tool]}, "", {}),
        ({"tools": [tool]}, "0" * 64, {}),
        ({"tools": [tool]}, "", {"missing": "string"}),
        ({"tools": [tool]}, "", {"action": "integer"}),
    ):
        with pytest.raises(ToolSchemaContractError):
            validate_live_tool_contract(
                listing,
                tool_name="reader",
                expected_schema_sha256=pinned_sha,
                required_argument_types=required,
            )
    with pytest.raises(ToolSchemaContractError, match="does not enumerate"):
        validate_live_tool_contract(
            [tool], tool_name="reader", required_argument_enums={"action": {"write"}}
        )
