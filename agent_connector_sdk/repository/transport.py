"""Branch-aware, blob-deduplicated repository transport into epistemic-graph.

One run enumerates every ref, walks each tree without content, fetches each
unique blob exactly once (streamed through bounded batches), and submits the
``(ref, path) -> blob`` memberships and tombstones alongside, so the engine
parses each blob once and projects branch membership by edge.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

from epistemic_graph.client import EpistemicGraphClient

from agent_connector_sdk.repository.batching import (
    Membership,
    RepositoryBatch,
    RepositoryBatcher,
)
from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.identity import _git_blob_object_id
from agent_connector_sdk.repository.indexing import (
    RepositoryBatchReceipt,
    ScopeHeader,
    submit_repository_batch,
)
from agent_connector_sdk.repository.manifest import (
    RepositoryIndexManifest,
    RepositoryManifestFile,
    RepositoryRefManifest,
    RepositorySnapshotManifest,
)
from agent_connector_sdk.repository.models import (
    RepositoryAuthentication,
    RepositoryBatchLimits,
    RepositoryFile,
    RepositoryTombstone,
)
from agent_connector_sdk.repository.plan import BlobFetch, IndexPlan, plan_index
from agent_connector_sdk.repository.provider import RepositorySnapshotProvider
from agent_connector_sdk.repository.walk import RefTree, walk_refs

__all__ = ["RepositoryIndexReceipt", "index_repository"]

# The engine's per-batch ref bound (`MAX_INDEX_SCOPE_REFS`).
_MAX_REFS = 4096


@dataclass(frozen=True)
class RepositoryIndexReceipt:
    """Source-side evidence retained after every batch is accepted by EG.

    ``manifest`` is the ``prior`` of the next run.
    """

    authentication: RepositoryAuthentication
    manifest: RepositoryIndexManifest
    batches: tuple[RepositoryBatchReceipt, ...]
    provider_pages: int
    blobs_fetched: int
    blobs_reused: int


def _repository_key(provider: RepositorySnapshotProvider) -> str:
    return f"{provider.name}:{provider.repository_id}"


def _header(
    provider: RepositorySnapshotProvider,
    trees: tuple[RefTree, ...],
    plan: IndexPlan,
    *,
    graph: str | None,
) -> ScopeHeader:
    refs = [
        {
            "ref_name": tree.ref.name,
            "revision_id": tree.ref.revision.revision_id,
            "status": "live",
        }
        for tree in trees
    ]
    refs.extend(
        {
            "ref_name": item.ref_name,
            "revision_id": item.snapshot.revision.revision_id,
            "status": "deleted",
        }
        for item in plan.deleted
    )
    if len(refs) > _MAX_REFS:
        raise RepositoryTransportError(
            f"repository declares more than {_MAX_REFS} refs"
        )
    return ScopeHeader(
        graph=graph, repository_id=_repository_key(provider), refs=tuple(refs)
    )


async def _fetch(
    provider: RepositorySnapshotProvider, item: BlobFetch
) -> RepositoryFile:
    content = await provider.fetch_blob(item.revision, item.blob_id)
    if _git_blob_object_id(content, width=len(item.blob_id)) != item.blob_id:
        raise RepositoryTransportError(f"blob content does not match {item.blob_id}")
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    return RepositoryFile(path=item.path, blob_digest=digest, content=content)


def _memberships(plan: IndexPlan, blob_id: str, digest: str) -> list[Membership]:
    return [(ref_name, path, digest) for path, ref_name in plan.members[blob_id]]


@dataclass
class _Run:
    """One run's batcher, accepted batch receipts and blob identities."""

    client: EpistemicGraphClient
    header: ScopeHeader
    batcher: RepositoryBatcher
    identities: dict[str, RepositoryManifestFile]
    receipts: list[RepositoryBatchReceipt] = field(default_factory=list)

    async def flush(self, batches: list[RepositoryBatch]) -> None:
        """Submit closed batches in order; each releases its blob bytes."""
        for batch in batches:
            receipt = await submit_repository_batch(self.client, self.header, batch)
            self.receipts.append(receipt)


async def _stream_new_blobs(
    provider: RepositorySnapshotProvider, plan: IndexPlan, run: _Run
) -> None:
    for item in plan.fetch:
        blob = await _fetch(provider, item)
        run.identities[item.blob_id] = RepositoryManifestFile(
            path=item.path,
            blob_id=item.blob_id,
            blob_digest=blob.blob_digest,
            byte_length=len(blob.content),
        )
        run.batcher.add_file(blob, _memberships(plan, item.blob_id, blob.blob_digest))
        await run.flush(run.batcher.drain())


def _queue_reused(plan: IndexPlan, run: _Run) -> None:
    for blob_id in sorted(plan.members.keys() & plan.known.keys()):
        digest = plan.known[blob_id].blob_digest
        run.batcher.add_versions(_memberships(plan, blob_id, digest))
    run.batcher.add_tombstones(plan.tombstones)


def _manifest(
    provider: RepositorySnapshotProvider,
    trees: tuple[RefTree, ...],
    plan: IndexPlan,
    *,
    identities: dict[str, RepositoryManifestFile],
) -> RepositoryIndexManifest:
    removed: dict[str, list[RepositoryTombstone]] = defaultdict(list)
    for ref_name, tombstone in plan.tombstones:
        removed[ref_name].append(tombstone)
    live = tuple(
        RepositoryRefManifest(
            ref_name=tree.ref.name,
            snapshot=RepositorySnapshotManifest(
                revision=tree.ref.revision,
                files=tuple(
                    identities[entry.blob_id].model_copy(update={"path": entry.path})
                    for entry in tree.entries
                ),
                tombstones=tuple(removed[tree.ref.name]),
            ),
        )
        for tree in trees
    )
    return RepositoryIndexManifest(
        repository_id=_repository_key(provider), refs=live + plan.deleted
    )


async def index_repository(
    provider: RepositorySnapshotProvider,
    client: EpistemicGraphClient,
    *,
    prior: RepositoryIndexManifest | None = None,
    limits: RepositoryBatchLimits | None = None,
    graph: str | None = None,
) -> RepositoryIndexReceipt:
    """Index every ref of one repository, parsing each unique blob once.

    ``prior`` is the previous run's ``receipt.manifest``: its blobs are not
    fetched again, and paths (or refs) missing since then become tombstones.
    EG commits each batch's projection durably into ``graph``.
    """
    bounds = limits or RepositoryBatchLimits()
    trees, pages = await walk_refs(provider, page_size=bounds.provider_page_size)
    plan = plan_index(trees, prior)
    run = _Run(
        client=client,
        header=_header(provider, trees, plan, graph=graph),
        batcher=RepositoryBatcher(bounds),
        identities=dict(plan.known),
    )
    await _stream_new_blobs(provider, plan, run)
    _queue_reused(plan, run)
    await run.flush(run.batcher.finish())
    return RepositoryIndexReceipt(
        authentication=provider.authentication,
        manifest=_manifest(provider, trees, plan, identities=run.identities),
        batches=tuple(run.receipts),
        provider_pages=pages,
        blobs_fetched=len(plan.fetch),
        blobs_reused=len(plan.members.keys() & plan.known.keys()),
    )
