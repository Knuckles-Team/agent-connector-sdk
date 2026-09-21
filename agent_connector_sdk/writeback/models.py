"""SDK-only source snapshots and dry-run diffs for connector write-back."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

__all__ = [
    "DryRunObservation",
    "SourceSnapshot",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceSnapshot(_Frozen):
    """A versioned source entity read before mutation or during reconciliation."""

    source_version: str = Field(min_length=1)
    fields: dict[str, JsonValue]
    observation: dict[str, JsonValue] = Field(default_factory=dict)


class DryRunObservation(_Frozen):
    """A side-effect-free diff against one current source version."""

    change_set_digest: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    desired_patch_digest: str = Field(min_length=1)
    changed_fields: tuple[str, ...]
    before: dict[str, JsonValue]
    after: dict[str, JsonValue]
