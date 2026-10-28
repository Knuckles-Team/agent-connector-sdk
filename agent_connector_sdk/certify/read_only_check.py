"""Check caller-supplied observed effects against a live tool contract."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from agent_connector_sdk.artifacts.side_effect import SideEffect

if TYPE_CHECKING:
    from agent_connector_sdk.artifacts.tool_facts import ToolContractFacts

__all__ = ["ReadOnlyOutcome", "ToolFixture", "check_read_only"]


class ReadOnlyOutcome(StrEnum):
    """Result of checking a caller-owned observation."""

    PROVEN = "proven"
    UNPROVEN = "unproven"
    READ_ONLY_VIOLATION = "read_only_violation"


class ToolFixture(BaseModel):
    """Observed effects for one exact live tool contract, supplied by the caller.

    This model does not collect or independently authenticate the observation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    tool: str = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    arguments: dict[str, Any]
    observed_effects: frozenset[SideEffect]


def check_read_only(
    facts: ToolContractFacts,
    fixture: ToolFixture | None,
    *,
    tool: str,
    fingerprint: str,
) -> ReadOnlyOutcome:
    """Refuse an absent, stale or write-bearing observation for a read-only claim."""
    if not facts.read_only:
        return ReadOnlyOutcome.PROVEN
    if fixture is None or fixture.tool != tool or fixture.fingerprint != fingerprint:
        return ReadOnlyOutcome.UNPROVEN
    if fixture.observed_effects & {
        SideEffect.WORKSPACE_WRITE,
        SideEffect.EXTERNAL_WRITE,
    }:
        return ReadOnlyOutcome.READ_ONLY_VIOLATION
    return ReadOnlyOutcome.PROVEN
