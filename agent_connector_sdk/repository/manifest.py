"""Deterministic repository snapshot manifests without source blob retention."""

from __future__ import annotations

import hashlib
import json
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_connector_sdk.repository.identity import _logical_path
from agent_connector_sdk.repository.models import (
    RepositoryRevision,
    RepositoryTombstone,
)

__all__ = ["RepositoryManifestFile", "RepositorySnapshotManifest"]


class RepositoryManifestFile(BaseModel):
    """Content identity retained after a source blob leaves transport memory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    blob_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    byte_length: int = Field(ge=0)

    @model_validator(mode="after")
    def _path_is_logical(self) -> Self:
        _logical_path(self.path)
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
        paths = [item.path for item in files]
        paths.extend(item.path for item in tombstones)
        if len(paths) != len(set(paths)):
            raise ValueError("snapshot manifest paths must be unique")
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "tombstones", tombstones)
        return self

    @property
    def fingerprint(self) -> str:
        """SHA-256 over canonical revision, file and tombstone evidence."""
        payload = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"
