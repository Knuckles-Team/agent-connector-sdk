"""Admission checks on the resource declaration carried by a connector pack."""

from __future__ import annotations

import json
from typing import Any

from scion_sdk.artifacts.pack import CapturedConnectorPack


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("connector resource declaration has duplicate keys")
        result[key] = value
    return result


def _resource_declaration(pack: CapturedConnectorPack, entry: Any) -> dict[str, Any]:
    section = entry.body
    end = section.offset + section.length
    if end > len(pack.archive.data):
        raise ValueError("connector resource declaration is truncated")
    try:
        declaration = json.loads(
            pack.archive.data[section.offset : end],
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("connector resource declaration is invalid") from exc
    if not isinstance(declaration, dict):
        raise ValueError("connector resource declaration must be an object")
    return declaration


def _refuse_typed_mappings(declaration: dict[str, Any]) -> None:
    mappings = declaration.get("schema_mappings", {})
    if not isinstance(mappings, dict):
        raise ValueError("connector schema mappings must be an object")
    for mapping in mappings.values():
        if not isinstance(mapping, dict):
            raise ValueError("connector schema mapping must be an object")
        if "datatypes" in mapping and mapping["datatypes"] != {}:
            raise ValueError(
                "typed source mappings require engine capability negotiation"
            )


def _require_supported_mapping_contract(pack: CapturedConnectorPack) -> None:
    """Refuse typed mappings until the connected engine can attest support."""
    for entry in pack.archive.entries:
        if entry.uri == "connector://resources":
            _refuse_typed_mappings(_resource_declaration(pack, entry))
