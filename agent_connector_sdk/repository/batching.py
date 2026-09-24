"""Bounded accumulation of unique blobs, ref memberships and tombstones."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.models import (
    RepositoryBatchLimits,
    RepositoryFile,
    RepositoryTombstone,
)

__all__: list[str] = []

# (ref name, path, blob sha256 digest)
Membership = tuple[str, str, str]


@dataclass
class RepositoryBatch:
    """One engine call: unique blobs plus the memberships riding with them."""

    files: list[RepositoryFile] = field(default_factory=list)
    versions: list[Membership] = field(default_factory=list)
    tombstones: list[tuple[str, RepositoryTombstone]] = field(default_factory=list)
    byte_count: int = 0

    def membership_count(self) -> int:
        """Memberships plus tombstones, bounded by ``max_file_versions``."""
        return len(self.versions) + len(self.tombstones)


class RepositoryBatcher:
    """Close a batch whenever the next item would cross a configured bound.

    A blob always shares its batch with its first membership, which names the
    path it is submitted under, so the engine can bind every submitted blob.
    """

    def __init__(self, limits: RepositoryBatchLimits) -> None:
        self.limits = limits
        self.batch = RepositoryBatch()
        self.ready: list[RepositoryBatch] = []

    def _rotate(self) -> None:
        if self.batch.files or self.batch.membership_count():
            self.ready.append(self.batch)
            self.batch = RepositoryBatch()

    def _reserve_membership(self) -> None:
        if self.batch.membership_count() >= self.limits.max_file_versions:
            self._rotate()

    def add_file(self, item: RepositoryFile, versions: Iterable[Membership]) -> None:
        """Add one unique blob followed by every membership that binds it."""
        size = len(item.content)
        if size > self.limits.max_file_bytes:
            raise RepositoryTransportError(
                f"repository file exceeds limit: {item.path}"
            )
        files_full = len(self.batch.files) >= self.limits.max_files
        bytes_full = bool(self.batch.files) and (
            self.batch.byte_count + size > self.limits.max_bytes
        )
        if files_full or bytes_full:
            self._rotate()
        self._reserve_membership()
        self.batch.files.append(item)
        self.batch.byte_count += size
        self.add_versions(versions)

    def add_versions(self, versions: Iterable[Membership]) -> None:
        """Add memberships of blobs submitted earlier or indexed by a prior run."""
        for version in versions:
            self._reserve_membership()
            self.batch.versions.append(version)

    def add_tombstones(
        self, tombstones: Iterable[tuple[str, RepositoryTombstone]]
    ) -> None:
        """Add ``(ref name, tombstone)`` pairs."""
        for tombstone in tombstones:
            self._reserve_membership()
            self.batch.tombstones.append(tombstone)

    def drain(self) -> list[RepositoryBatch]:
        """Return and forget the batches closed so far."""
        ready, self.ready = self.ready, []
        return ready

    def finish(self) -> list[RepositoryBatch]:
        """Close the open batch and return every remaining batch."""
        self._rotate()
        return self.drain()
