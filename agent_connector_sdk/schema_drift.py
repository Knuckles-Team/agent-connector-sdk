"""Pure normalized source-contract classification and quarantine reports."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = [
    "DriftClassification",
    "EvolutionPolicy",
    "SchemaContract",
    "SchemaDriftReport",
    "classify_schema_drift",
]


class DriftClassification(StrEnum):
    """Whether a source contract may proceed to ingestion."""

    COMPATIBLE = "COMPATIBLE"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    BREAKING = "BREAKING"


class EvolutionPolicy(StrEnum):
    """Changes explicitly permitted by the connector owner."""

    REVIEW = "review"
    OPTIONAL_FIELDS = "optional_fields"


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


class SchemaDriftReport(BaseModel):
    """Metadata-only quarantine evidence; no records or resolved credentials."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    source: str
    stream: str
    tenant: str | None
    old_schema_digest: str | None
    new_schema_digest: str | None
    affected_fields: tuple[str, ...]
    classification: DriftClassification
    observed_sample_digest: str
    reason_codes: tuple[str, ...]


# Each entry carries field, stable reason, and severity. Unknown schema features
# remain reviewable rather than being guessed compatible.
_Change = tuple[str, str, DriftClassification]


def _property_changes(
    old: dict[str, Any], new: dict[str, Any], path: str, policy: EvolutionPolicy
) -> list[_Change]:
    before, after = old.get("properties", {}), new.get("properties", {})
    if not isinstance(before, dict) or not isinstance(after, dict):
        return [(path, "UNKNOWN_PROPERTIES", DriftClassification.REQUIRES_REVIEW)]
    changes: list[_Change] = []
    required = set(old.get("required", [])) | set(new.get("required", []))
    for name in sorted(before.keys() | after.keys()):
        field = f"{path}/properties/{name}"
        if name not in after:
            level = (
                DriftClassification.BREAKING
                if name in required
                else DriftClassification.REQUIRES_REVIEW
            )
            changes.append((field, "FIELD_REMOVED", level))
        elif name not in before:
            level = DriftClassification.REQUIRES_REVIEW
            if name not in required and policy is EvolutionPolicy.OPTIONAL_FIELDS:
                level = DriftClassification.COMPATIBLE
            changes.append((field, "FIELD_ADDED", level))
        else:
            changes.extend(_changes(before[name], after[name], field, policy))
    return changes


def _changes(old: Any, new: Any, path: str, policy: EvolutionPolicy) -> list[_Change]:
    if old == new:
        return []
    if not isinstance(old, dict) or not isinstance(new, dict):
        return [(path, "UNKNOWN_SCHEMA_CHANGE", DriftClassification.REQUIRES_REVIEW)]
    changes = _property_changes(old, new, path, policy)
    for key in sorted(old.keys() | new.keys()):
        if key == "properties" or old.get(key) == new.get(key):
            continue
        field = f"{path}/{key}"
        if key == "items":
            changes.extend(_changes(old.get(key), new.get(key), field, policy))
        elif key == "type":
            changes.append((field, "TYPE_CHANGED", DriftClassification.BREAKING))
        else:
            reason = {
                "required": "REQUIREDNESS_CHANGED",
                "enum": "ENUM_CHANGED",
                "const": "ENUM_CHANGED",
            }.get(key, "UNKNOWN_SCHEMA_CHANGE")
            changes.append((field, reason, DriftClassification.REQUIRES_REVIEW))
    return changes


def _contract_changes(
    prior: SchemaContract | None,
    current: SchemaContract | None,
    policy: EvolutionPolicy,
) -> list[_Change]:
    if prior is None or current is None:
        changes = [("/", "MISSING_SCHEMA", DriftClassification.REQUIRES_REVIEW)]
    else:
        changes = _changes(
            json.loads(prior.canonical_schema),
            json.loads(current.canonical_schema),
            "",
            policy,
        )
        if prior.identifier_fields != current.identifier_fields:
            changes.append(("/", "IDENTIFIER_CHANGED", DriftClassification.BREAKING))
    return changes


def _classification(changes: list[_Change]) -> DriftClassification:
    levels = {entry[2] for entry in changes}
    for level in (DriftClassification.BREAKING, DriftClassification.REQUIRES_REVIEW):
        if level in levels:
            return level
    return DriftClassification.COMPATIBLE


def classify_schema_drift(
    prior: SchemaContract | None,
    current: SchemaContract | None,
    *,
    source: str,
    stream: str,
    tenant: str | None,
    observed_sample_digest: str,
    policy: EvolutionPolicy = EvolutionPolicy.REVIEW,
) -> SchemaDriftReport:
    """Classify changes; unknown evidence never authorizes submission."""
    changes = _contract_changes(prior, current, policy)
    classification = _classification(changes)
    return SchemaDriftReport(
        source=source,
        stream=stream,
        tenant=tenant,
        old_schema_digest=None if prior is None else prior.digest(),
        new_schema_digest=None if current is None else current.digest(),
        affected_fields=tuple(sorted({entry[0] for entry in changes})),
        classification=classification,
        observed_sample_digest=observed_sample_digest,
        reason_codes=tuple(sorted({entry[1] for entry in changes})),
    )
