"""Generate linked JSON Schemas from the public disclosure wire models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scion_sdk.mcp.schema_disclosure import SchemaFragment, SchemaManifest


def schema_documents():
    manifest = SchemaManifest.model_json_schema()
    fragment = SchemaFragment.model_json_schema()
    identity = {key: manifest[key] for key in ("properties", "required", "type")}
    shared = set(identity["properties"])
    return {
        "schema-manifest.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"SchemaIdentity": identity},
            "$ref": "#/$defs/SchemaIdentity",
            "title": manifest["title"],
            "description": manifest["description"],
            "unevaluatedProperties": False,
        },
        "schema-fragment.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "schema-manifest.schema.json#/$defs/SchemaIdentity",
            "title": fragment["title"],
            "description": fragment["description"],
            "properties": {
                key: value
                for key, value in fragment["properties"].items()
                if key not in shared
            },
            "required": [key for key in fragment["required"] if key not in shared],
            "unevaluatedProperties": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parents[1] / "docs" / "reference"
    for name, schema in schema_documents().items():
        text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        path = directory / name
        if args.check:
            if path.read_text() != text:
                raise SystemExit(f"Stale schema artifact: {name}")
        else:
            path.write_text(text)


if __name__ == "__main__":
    main()
