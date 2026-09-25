"""Pure, deterministic planning of one branch-aware repository run.

Given every ref's tree and the previous run's manifest, decide which unique
blobs must be fetched (each exactly once, under its lexicographically smallest
path), which blobs are already indexed, every ``(ref, path)`` membership, and
the tombstones for paths that left a ref or refs that disappeared.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from agent_connector_sdk.repository.manifest import (
    RepositoryIndexManifest,
    RepositoryManifestFile,
    RepositoryRefManifest,
    RepositorySnapshotManifest,
)
from agent_connector_sdk.repository.models import (
    RepositoryRevision,
    RepositoryTombstone,
)
from agent_connector_sdk.repository.refs import RepositoryTreeEntry
from agent_connector_sdk.repository.walk import RefTree

__all__: list[str] = []


@dataclass(frozen=True)
class BlobFetch:
    """One unique blob to fetch, named by its smallest path."""

    blob_id: str
    path: str
    revision: RepositoryRevision


@dataclass(frozen=True)
class IndexPlan:
    """Everything a run submits, in deterministic order."""

    fetch: tuple[BlobFetch, ...]
    known: dict[str, RepositoryManifestFile]
    members: dict[str, tuple[tuple[str, str], ...]]
    tombstones: tuple[tuple[str, RepositoryTombstone], ...]
    deleted: tuple[RepositoryRefManifest, ...]


def _prior_refs(
    prior: RepositoryIndexManifest | None,
) -> dict[str, RepositoryRefManifest]:
    if prior is None:
        return {}
    return {item.ref_name: item for item in prior.refs if not item.deleted}


def _successor(
    removed: RepositoryManifestFile, added: dict[str, list[str]]
) -> str | None:
    candidates = added.get(removed.blob_id)
    return min(candidates) if candidates else None


def _ref_tombstones(
    entries: tuple[RepositoryTreeEntry, ...], prior: RepositorySnapshotManifest
) -> tuple[RepositoryTombstone, ...]:
    current = {entry.path: entry.blob_id for entry in entries}
    before = {item.path for item in prior.files}
    added: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        if entry.path not in before:
            added[entry.blob_id].append(entry.path)
    return tuple(
        RepositoryTombstone(
            path=item.path,
            prior_blob_digest=item.blob_digest,
            successor_path=None if item.path in current else _successor(item, added),
        )
        for item in prior.files
        if current.get(item.path) != item.blob_id
    )


def _deleted(
    trees: tuple[RefTree, ...], prior: dict[str, RepositoryRefManifest]
) -> tuple[RepositoryRefManifest, ...]:
    live = {tree.ref.name for tree in trees}
    return tuple(
        RepositoryRefManifest(
            ref_name=name,
            deleted=True,
            snapshot=RepositorySnapshotManifest(
                revision=item.snapshot.revision,
                files=(),
                tombstones=tuple(
                    RepositoryTombstone(
                        path=file.path, prior_blob_digest=file.blob_digest
                    )
                    for file in item.snapshot.files
                ),
            ),
        )
        for name, item in sorted(prior.items())
        if name not in live
    )


def _tombstones(
    trees: tuple[RefTree, ...],
    prior: dict[str, RepositoryRefManifest],
    deleted: tuple[RepositoryRefManifest, ...],
) -> tuple[tuple[str, RepositoryTombstone], ...]:
    removed = [
        (tree.ref.name, tombstone)
        for tree in trees
        if tree.ref.name in prior
        for tombstone in _ref_tombstones(tree.entries, prior[tree.ref.name].snapshot)
    ]
    removed.extend(
        (item.ref_name, tombstone)
        for item in deleted
        for tombstone in item.snapshot.tombstones
    )
    return tuple(sorted(removed, key=lambda pair: (pair[0], pair[1].path)))


def plan_index(
    trees: tuple[RefTree, ...], prior: RepositoryIndexManifest | None
) -> IndexPlan:
    """Plan one run: unique blobs to fetch, reused blobs, members, tombstones."""
    prior_refs = _prior_refs(prior)
    known = {
        file.blob_id: file
        for item in prior_refs.values()
        for file in item.snapshot.files
        if file.parse_status == "success"
    }
    members: dict[str, list[tuple[str, str]]] = defaultdict(list)
    sources: dict[str, RepositoryRevision] = {}
    for tree in trees:
        for entry in tree.entries:
            members[entry.blob_id].append((entry.path, tree.ref.name))
            sources.setdefault(entry.blob_id, tree.ref.revision)
    ordered = {blob_id: tuple(sorted(pairs)) for blob_id, pairs in members.items()}
    fetch = sorted(
        (
            BlobFetch(blob_id=blob_id, path=pairs[0][0], revision=sources[blob_id])
            for blob_id, pairs in ordered.items()
            if blob_id not in known
        ),
        key=lambda item: (item.path, item.blob_id),
    )
    deleted = _deleted(trees, prior_refs)
    return IndexPlan(
        fetch=tuple(fetch),
        known=known,
        members=ordered,
        tombstones=_tombstones(trees, prior_refs, deleted),
        deleted=deleted,
    )
