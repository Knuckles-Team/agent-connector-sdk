"""Validated stage declarations for future concurrent source execution."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["StageDependency", "StageDescriptor", "StageLimits"]


class _StageModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class StageLimits(_StageModel):
    """Explicit host-admitted resource and deadline bounds."""

    max_active_stages: int = Field(ge=1, le=2**31 - 1)
    page_rows: int = Field(ge=1, le=2**31 - 1)
    page_bytes: int = Field(ge=1, le=2**63 - 1)
    queued_pages: int = Field(ge=1, le=2**31 - 1)
    deadline_ms: int = Field(ge=1, le=2**63 - 1)


class StageDependency(_StageModel):
    """A prerequisite stage and its required durable receipt identity."""

    stage_id: str = Field(min_length=1)
    receipt_id: str = Field(min_length=1)

    @field_validator("stage_id", "receipt_id")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("stage identity must not be blank")
        return value


class StageDescriptor(_StageModel):
    """A stream bound to admitted authority, dependencies and resource limits."""

    stage_id: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    connector: str = Field(min_length=1)
    source: str = Field(min_length=1)
    stream: str = Field(min_length=1)
    manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    dependencies: tuple[StageDependency, ...] = ()
    admitted_limits: StageLimits

    @field_validator("stage_id", "tenant", "connector", "source", "stream")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("stage identity must not be blank")
        return value


def validate_stage_graph(
    stages: tuple[StageDescriptor, ...], connector: str, tenant: str | None
) -> None:
    """Refuse missing authority, duplicate streams and cyclic dependencies."""
    if not isinstance(stages, tuple) or any(
        not isinstance(stage, StageDescriptor) for stage in stages
    ):
        raise ValueError("stages must be a tuple of stage descriptors")
    by_id = {stage.stage_id: stage for stage in stages}
    if len(by_id) != len(stages):
        raise ValueError("duplicate stage identity")
    if stages and (
        not tenant
        or any(
            stage.tenant != tenant or stage.connector != connector for stage in stages
        )
    ):
        raise ValueError("stage authority does not match target")
    if len({stage.stream for stage in stages}) != len(stages):
        raise ValueError("duplicate stage stream")
    edges = {
        stage.stage_id: {dep.stage_id for dep in stage.dependencies} for stage in stages
    }
    for stage in stages:
        if len(edges[stage.stage_id]) != len(stage.dependencies):
            raise ValueError("duplicate stage dependency")
        if not edges[stage.stage_id] <= by_id.keys():
            raise ValueError("unknown stage dependency")
    dependents: dict[str, list[str]] = {stage_id: [] for stage_id in by_id}
    for stage_id, dependencies in edges.items():
        for dependency in dependencies:
            dependents[dependency].append(stage_id)
    ready = [stage_id for stage_id, dependencies in edges.items() if not dependencies]
    seen: set[str] = set()
    while ready:
        stage_id = ready.pop()
        seen.add(stage_id)
        for dependent in dependents[stage_id]:
            edges[dependent].remove(stage_id)
            if not edges[dependent]:
                ready.append(dependent)
    if len(seen) != len(stages):
        raise ValueError("cyclic stage dependencies")
