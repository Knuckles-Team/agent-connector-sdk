"""Deterministic repository manifests without source blob retention.

A manifest is also the input of the next run: its per-ref files let the
transport tombstone paths that left a ref and reuse the content digest of every
blob already indexed, so a re-run fetches and parses only new blobs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_connector_sdk.repository.identity import _immutable_git_id, _logical_path
from agent_connector_sdk.repository.models import (
    RepositoryRevision,
    RepositoryTombstone,
)

__all__ = [
    "RepositoryIndexManifest",
    "RepositoryManifestFile",
    "RepositoryRefManifest",
    "RepositorySnapshotManifest",
]


def _fingerprint(model: BaseModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _require_unique_paths(
    items: tuple[RepositoryManifestFile, ...] | tuple[RepositoryTombstone, ...],
    kind: str,
) -> None:
    # A path whose blob changed is both a file and a tombstone of one ref, so
    # uniqueness holds within each collection, not across them.
    if len({item.path for item in items}) != len(items):
        raise ValueError(f"snapshot manifest {kind} paths must be unique")


class RepositoryManifestFile(BaseModel):
    """Content identity retained after a source blob leaves transport memory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    blob_id: str
    blob_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    byte_length: int = Field(ge=0)

    @model_validator(mode="after")
    def _identity_is_canonical(self) -> Self:
        _logical_path(self.path)
        _immutable_git_id(self.blob_id, field_name="blob_id")
        return self


class RepositorySnapshotManifest(BaseModel):
    """Canonical file and tombstone evidence for one immutable revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    revision: RepositoryRevision
    files: tuple[RepositoryManifestFile, ...]
    tombstones: tuple[RepositoryTombstone, ...] = ()

    @model_validator(mode="after")
    def _canonical_order(self) -> Self:
        files = tuple(sorted(self.files, key=lambda item: item.path))
        tombstones = tuple(sorted(self.tombstones, key=lambda item: item.path))
        _require_unique_paths(files, "file")
        _require_unique_paths(tombstones, "tombstone")
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "tombstones", tombstones)
        return self

    @property
    def fingerprint(self) -> str:
        """SHA-256 over canonical revision, file and tombstone evidence."""
        return _fingerprint(self)


class RepositoryRefManifest(BaseModel):
    """One ref's snapshot; a deleted ref keeps its last revision and tombstones."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref_name: str = Field(min_length=1)
    deleted: bool = False
    snapshot: RepositorySnapshotManifest


class RepositoryIndexManifest(BaseModel):
    """Every ref of one repository run, sorted by ref name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository_id: str = Field(min_length=1)
    refs: tuple[RepositoryRefManifest, ...]

    @model_validator(mode="after")
    def _canonical_order(self) -> Self:
        refs = tuple(sorted(self.refs, key=lambda item: item.ref_name))
        if len({item.ref_name for item in refs}) != len(refs):
            raise ValueError("repository manifest ref names must be unique")
        object.__setattr__(self, "refs", refs)
        return self

    @property
    def fingerprint(self) -> str:
        """SHA-256 over every ref's canonical snapshot evidence."""
        return _fingerprint(self)
