"""Immutable source-side records for repository snapshot transport.

These models describe provider transport only. They deliberately do not model
symbols, semantic edges, graph mutations, parse diagnostics, or durable cursors;
epistemic-graph owns those contracts and effects.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_connector_sdk.repository.identity import (
    _immutable_git_id,
    _logical_path,
    _sha256_digest,
    _validate_page,
)

__all__ = [
    "RepositoryAuthentication",
    "RepositoryBatchLimits",
    "RepositoryFile",
    "RepositoryPage",
    "RepositoryRevision",
    "RepositoryTombstone",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _PathsPage(_Frozen, ABC):
    """One paged listing whose items carry a path: unique, no empty continuation.

    Shared by every provider page type (file pages, tree pages, ...): a
    subclass supplies the paths its own items carry.
    """

    next_cursor: str | None = Field(default=None, min_length=1)

    @abstractmethod
    def _page_paths(self) -> list[str]:
        """The paths this page's items carry, in provider order."""

    @model_validator(mode="after")
    def _paths_are_unique(self) -> Self:
        _validate_page(self._page_paths(), self.next_cursor, label=type(self).__name__)
        return self


class RepositoryRevision(_Frozen):
    """One provider/project revision pinned to an immutable commit and tree."""

    provider: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    tree_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _revision_is_immutable(self) -> Self:
        object.__setattr__(
            self,
            "revision_id",
            _immutable_git_id(self.revision_id, field_name="revision_id"),
        )
        object.__setattr__(
            self, "tree_id", _immutable_git_id(self.tree_id, field_name="tree_id")
        )
        return self


class RepositoryAuthentication(_Frozen):
    """Non-secret evidence identifying the authenticated provider session."""

    provider: str = Field(min_length=1)
    principal: str = Field(min_length=1)
    mechanism: str = Field(min_length=1)
    credential_reference_digest: str

    @model_validator(mode="after")
    def _digest_is_sha256(self) -> Self:
        object.__setattr__(
            self,
            "credential_reference_digest",
            _sha256_digest(
                self.credential_reference_digest,
                field_name="credential_reference_digest",
            ),
        )
        return self


class RepositoryFile(_Frozen):
    """One immutable blob at a logical path in a repository revision."""

    path: str
    blob_digest: str
    content: bytes

    @model_validator(mode="after")
    def _identity_matches_content(self) -> Self:
        object.__setattr__(self, "path", _logical_path(self.path))
        expected = f"sha256:{hashlib.sha256(self.content).hexdigest()}"
        digest = _sha256_digest(self.blob_digest, field_name="blob_digest")
        if digest != expected:
            raise ValueError("blob_digest does not match content")
        object.__setattr__(self, "blob_digest", digest)
        return self


class RepositoryTombstone(_Frozen):
    """A path removed or renamed since the preceding admitted revision."""

    path: str
    prior_blob_digest: str
    successor_path: str | None = None

    @model_validator(mode="after")
    def _validate_identity(self) -> Self:
        object.__setattr__(self, "path", _logical_path(self.path))
        object.__setattr__(
            self,
            "prior_blob_digest",
            _sha256_digest(self.prior_blob_digest, field_name="prior_blob_digest"),
        )
        if self.successor_path is not None:
            object.__setattr__(
                self, "successor_path", _logical_path(self.successor_path)
            )
        return self


class RepositoryPage(_PathsPage):
    """One provider page bound to the exact requested immutable revision."""

    revision: RepositoryRevision
    files: tuple[RepositoryFile, ...] = ()
    tombstones: tuple[RepositoryTombstone, ...] = ()

    def _page_paths(self) -> list[str]:
        paths = [item.path for item in self.files]
        paths.extend(item.path for item in self.tombstones)
        return paths


class RepositoryBatchLimits(_Frozen):
    """Bounds for one epistemic-graph repository-resolution call."""

    max_files: int = Field(default=4096, ge=1, le=100_000)
    max_bytes: int = Field(default=32 * 1024 * 1024, ge=1, le=256 * 1024 * 1024)
    max_file_bytes: int = Field(default=4 * 1024 * 1024, ge=1, le=64 * 1024 * 1024)
    provider_page_size: int = Field(default=1000, ge=1, le=10_000)

    @model_validator(mode="after")
    def _file_fits_batch(self) -> Self:
        if self.max_file_bytes > self.max_bytes:
            raise ValueError("max_file_bytes must not exceed max_bytes")
        return self
