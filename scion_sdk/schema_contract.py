"""Immutable normalized source schema snapshots and deterministic identity."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = ["SchemaContract"]


_PRESENTATION = frozenset({"title", "description", "examples", "$comment", "default"})
_SCHEMA_MAPS = frozenset(
    {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
)


_SCHEMA_VALUES = frozenset(
    {
        "",
        "items",
        "additionalItems",
        "additionalProperties",
        "unevaluatedItems",
        "unevaluatedProperties",
        "propertyNames",
        "contains",
        "not",
        "if",
        "then",
        "else",
        "contentSchema",
        "allOf",
        "anyOf",
        "oneOf",
        "prefixItems",
    }
)


def _normalize(value: Any, keyword: str = "") -> Any:
    if keyword in {"enum", "required", "type"}:
        return sorted(value, key=_json) if isinstance(value, list) else value
    if keyword in _SCHEMA_MAPS and isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in sorted(value.items())}
    # Unknown keywords and literal values may contain semantic keys named title
    # or description. Preserve them verbatim rather than infer schema positions.
    if keyword not in _SCHEMA_VALUES:
        return value
    return _normalize_schema(value)


def _normalize_schema(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item, str(key))
            for key, item in sorted(value.items())
            if key not in _PRESENTATION
        }
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


class SchemaContract(BaseModel):
    """An immutable normalized JSON Schema snapshot, without graph schema authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    canonical_schema: str
    identifier_fields: tuple[str, ...] = ()

    @field_validator("canonical_schema")
    @classmethod
    def _canonical(cls, value: str) -> str:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("source contract must be a JSON Schema object")
        return _json(_normalize(parsed))

    @field_validator("identifier_fields")
    @classmethod
    def _identifiers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))

    @classmethod
    def from_schema(
        cls, schema: Mapping[str, Any], *, identifier_fields: tuple[str, ...] = ()
    ) -> SchemaContract:
        """Normalize semantic sets and ignore presentation-only changes."""
        return cls(
            canonical_schema=_json(_normalize(schema)),
            identifier_fields=tuple(sorted(set(identifier_fields))),
        )

    def digest(self) -> str:
        """Bind normalized schema and identifier semantics deterministically."""
        return hashlib.sha256(
            _json([self.canonical_schema, self.identifier_fields]).encode()
        ).hexdigest()
