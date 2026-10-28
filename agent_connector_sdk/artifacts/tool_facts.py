"""Public estimates for canonical captured tool bodies.

The estimate is not a tokenizer count and does not publish pack annotations.
Callers may replace it with a measured tokenizer count where available.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "DEFAULT_SCHEMA_BYTES_PER_TOKEN",
    "SideEffect",
    "ToolContractFacts",
    "schema_tokens",
]

DEFAULT_SCHEMA_BYTES_PER_TOKEN = 4


def schema_tokens(body: str) -> int:
    """Estimate tokens from the UTF-8 bytes of a canonical tool body."""
    byte_count = len(body.encode("utf-8"))
    return (
        byte_count + DEFAULT_SCHEMA_BYTES_PER_TOKEN - 1
    ) // DEFAULT_SCHEMA_BYTES_PER_TOKEN


class SideEffect(StrEnum):
    """Closed set of tool effects used by contract facts."""

    NONE = "none"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_WRITE = "external_write"
    NETWORK = "network"


class ToolContractFacts(BaseModel):
    """Typed facts declared or inferred for a captured tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    read_only: bool
    side_effects: frozenset[SideEffect]
    arg_schema: dict[str, Any]
    schema_tokens: int = Field(ge=0)
    declared_by: Literal["connector", "mcp_hint", "default"]

    @model_validator(mode="after")
    def _validate_effects(self) -> Self:
        if SideEffect.NONE in self.side_effects and len(self.side_effects) > 1:
            raise ValueError("none cannot be combined with another side effect")
        writes = {SideEffect.WORKSPACE_WRITE, SideEffect.EXTERNAL_WRITE}
        if self.read_only and self.side_effects.intersection(writes):
            raise ValueError("read-only tools cannot declare write effects")
        return self
