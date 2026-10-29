"""Published linked schemas retain the generated model constraints."""

import copy
import json
import runpy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from agent_connector_sdk.mcp.schema_disclosure import (
    SchemaFragment,
    SchemaManifest,
    build_schema_disclosure,
    read_schema_fragment,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R045")
def test_schema_artifacts_are_generated_from_current_models():
    generator = runpy.run_path(str(ROOT / "scripts/generate_schema_disclosure.py"))
    for name, schema in generator["schema_documents"]().items():
        actual = (ROOT / "docs/reference" / name).read_text()
        assert actual == json.dumps(schema, indent=2, sort_keys=True) + "\n"
        Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("artifact", ["manifest", "fragment"])
@pytest.mark.parametrize("damage", [None, "extra", "missing", "digest", "bounds"])
def test_linked_artifacts_match_model_schema_validation(artifact, damage):
    schemas = {
        path.name: json.loads(path.read_text())
        for path in (ROOT / "docs/reference").glob("schema-*.schema.json")
    }
    registry = Registry().with_resources(
        (name, Resource.from_contents(schema)) for name, schema in schemas.items()
    )
    disclosure = build_schema_disclosure(
        ({"type": "object"}, {"type": "null"}),
        operation="readEntry",
        alias="read_entry",
        source_sha256="a" * 64,
    )
    model = SchemaManifest if artifact == "manifest" else SchemaFragment
    value = disclosure.manifest.model_dump()
    if artifact == "fragment":
        value = read_schema_fragment(
            disclosure, 0, expected_sha256=value["schema_sha256"]
        )
    value = copy.deepcopy(value)
    if damage == "extra":
        value["undeclared"] = True
    elif damage == "missing":
        del value["operation"]
    elif damage == "digest":
        value["input_schema_sha256"] = "invalid"
    elif damage == "bounds":
        value["fragment_count"] = 0
    linked = Draft202012Validator(
        schemas[f"schema-{artifact}.schema.json"], registry=registry
    )
    ordinary = Draft202012Validator(model.model_json_schema())
    assert linked.is_valid(value) == ordinary.is_valid(value) == (damage is None)
