"""Pure normalized source-contract classification and quarantine reports."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_connector_sdk.schema_contract import SchemaContract

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


def _addition_level(required: bool, policy: EvolutionPolicy) -> DriftClassification:
    if not required and policy is EvolutionPolicy.OPTIONAL_FIELDS:
        return DriftClassification.COMPATIBLE
    return DriftClassification.REQUIRES_REVIEW


def _property_changes(
    old: dict[str, Any], new: dict[str, Any], path: str, *, policy: EvolutionPolicy
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
            level = _addition_level(name in required, policy)
            changes.append((field, "FIELD_ADDED", level))
        else:
            changes.extend(_changes(before[name], after[name], field, policy=policy))
    return changes


def _changes(
    old: Any, new: Any, path: str, *, policy: EvolutionPolicy
) -> list[_Change]:
    if old == new:
        return []
    if not isinstance(old, dict) or not isinstance(new, dict):
        return [(path, "UNKNOWN_SCHEMA_CHANGE", DriftClassification.REQUIRES_REVIEW)]
    changes = _property_changes(old, new, path, policy=policy)
    for key in sorted(old.keys() | new.keys()):
        if key == "properties" or old.get(key) == new.get(key):
            continue
        field = f"{path}/{key}"
        if key == "items":
            changes.extend(_changes(old.get(key), new.get(key), field, policy=policy))
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
            policy=policy,
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
