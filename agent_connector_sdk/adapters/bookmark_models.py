"""Bounded contracts for an offline, host-authorized bookmark export."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Text = Annotated[str, Field(min_length=1, max_length=256)]


class BookmarkReadError(ValueError):
    """A redacted, typed refusal to read an export."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class BookmarkRequest(BaseModel):
    """A relative file selected within the host-authorized root."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    relative_path: Text
    export_revision: Literal["social-v1"]
    vocabulary_revision: Text
    file_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    vocabulary_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    offset: int = Field(default=0, ge=0, le=10_000)
    page_size: int = Field(default=100, ge=1, le=100)
    max_file_bytes: int = Field(default=1_048_576, ge=1, le=1_048_576)

    @model_validator(mode="after")
    def require_digest_for_continuation(self) -> BookmarkRequest:
        if self.offset and (self.file_sha256 is None or self.vocabulary_sha256 is None):
            raise ValueError("continuation requires file and vocabulary digests")
        return self


class BookmarkEnvelope(BaseModel):
    """A record and its deterministic, source-attributed extraction."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    bookmark_id: Text
    record_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(max_length=65_536)
    source_offset: int = Field(ge=0)
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    export_revision: Literal["social-v1"]
    vocabulary_revision: Text
    vocabulary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hashtags: tuple[str, ...]
    mentions: tuple[str, ...]
    tools: tuple[str, ...]
    urls: tuple[str, ...]
    domains: tuple[tuple[str, str | None], ...]
    raw: dict[str, JsonValue]


class BookmarkResult(BaseModel):
    """The complete result for one immutable export."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    vocabulary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bookmarks: tuple[BookmarkEnvelope, ...] = Field(max_length=100)
    next_offset: int | None = Field(default=None, ge=0)
