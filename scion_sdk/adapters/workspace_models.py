"""Bounded contracts for host-authorized workspace reads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WorkspaceFormat = Literal["pdf", "docx", "xlsx", "text", "vtt", "srt"]
WorkspaceReason = Literal[
    "unsupported_type",
    "invalid_content",
    "parser_unavailable",
    "access_denied",
    "limit_exceeded",
    "cancelled",
]


class WorkspaceFile(BaseModel):
    """One file in an immutable, host-provided snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    relative_path: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(ge=0, le=10_485_760)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    format: WorkspaceFormat
    parser_revision: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def relative_identity(self) -> WorkspaceFile:
        if self.relative_path.startswith("/") or "\x00" in self.relative_path:
            raise ValueError("invalid relative path")
        return self


class WorkspaceRequest(BaseModel):
    """One bounded read under a host-supplied root authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    tenant: str = Field(min_length=1, max_length=256)
    root_authority: str = Field(min_length=1, max_length=256)
    files: tuple[WorkspaceFile, ...] = Field(min_length=1, max_length=100, strict=False)
    max_tasks: int = Field(ge=1, le=16)
    max_file_bytes: int = Field(ge=1, le=10_485_760)
    max_expanded_bytes: int = Field(ge=1, le=50_000_000)
    max_pages: int = Field(ge=1, le=100)
    deadline_seconds: float = Field(gt=0, le=30, allow_inf_nan=False)

    @model_validator(mode="after")
    def unique_paths(self) -> WorkspaceRequest:
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate relative path")
        return self


class WorkspaceLocation(BaseModel):
    """A text segment and its source location."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    text: str = Field(max_length=1_000_000)
    line: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    sheet: str | None = Field(default=None, max_length=256)
    cell: str | None = Field(default=None, max_length=32)
    start: str | None = Field(default=None, max_length=32)
    end: str | None = Field(default=None, max_length=32)


class WorkspaceOutcome(BaseModel):
    """The successful read or typed refusal for one manifest entry."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    file: WorkspaceFile
    outcome: Literal["ok", "failed"]
    reason: WorkspaceReason | None = None
    locations: tuple[WorkspaceLocation, ...] = ()
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent_outcome(self) -> WorkspaceOutcome:
        if (self.outcome == "ok") != (self.reason is None):
            raise ValueError("outcome and reason disagree")
        if self.reason is not None and self.locations:
            raise ValueError("failed files cannot return locations")
        return self
