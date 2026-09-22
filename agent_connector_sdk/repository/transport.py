"""Authenticated immutable repository paging and EG batch transport."""

from __future__ import annotations

from dataclasses import dataclass

from epistemic_graph.client import EpistemicGraphClient

from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.indexing import (
    RepositoryBatchReceipt,
    _RepositoryBatcher,
    submit_repository_batch,
)
from agent_connector_sdk.repository.manifest import (
    RepositoryManifestFile,
    RepositorySnapshotManifest,
)
from agent_connector_sdk.repository.models import (
    RepositoryAuthentication,
    RepositoryBatchLimits,
    RepositoryPage,
    RepositoryRevision,
    RepositoryTombstone,
)
from agent_connector_sdk.repository.provider import RepositorySnapshotProvider

__all__ = ["RepositoryIndexReceipt", "index_repository_snapshot"]


@dataclass(frozen=True)
class RepositoryIndexReceipt:
    """Source-side evidence retained after every batch is accepted by EG."""

    revision: RepositoryRevision
    authentication: RepositoryAuthentication
    manifest: RepositorySnapshotManifest
    batches: tuple[RepositoryBatchReceipt, ...]
    provider_pages: int


def _validate_provider(
    provider: RepositorySnapshotProvider, revision: RepositoryRevision
) -> RepositoryAuthentication:
    authentication = provider.authentication
    if provider.name != revision.provider or authentication.provider != provider.name:
        raise RepositoryTransportError("provider, authentication and revision disagree")
    return authentication


def _accept_paths(
    page: RepositoryPage,
    *,
    seen_paths: set[str],
    tombstones: list[RepositoryTombstone],
    manifest_files: list[RepositoryManifestFile],
) -> None:
    paths = [item.path for item in page.files]
    paths.extend(item.path for item in page.tombstones)
    if any(path in seen_paths for path in paths):
        raise RepositoryTransportError("provider repeated a repository path")
    seen_paths.update(paths)
    tombstones.extend(page.tombstones)
    manifest_files.extend(
        RepositoryManifestFile(
            path=item.path,
            blob_digest=item.blob_digest,
            byte_length=len(item.content),
        )
        for item in page.files
    )


async def _accept_files(
    page: RepositoryPage,
    *,
    batcher: _RepositoryBatcher,
    client: EpistemicGraphClient,
    batches: list[RepositoryBatchReceipt],
) -> None:
    for item in page.files:
        ready = batcher.add(item)
        if ready:
            batches.append(await submit_repository_batch(client, ready))


async def index_repository_snapshot(
    provider: RepositorySnapshotProvider,
    client: EpistemicGraphClient,
    revision: RepositoryRevision,
    *,
    limits: RepositoryBatchLimits | None = None,
) -> RepositoryIndexReceipt:
    """Fetch and index one immutable revision with bounded memory and calls."""
    bounds = limits or RepositoryBatchLimits()
    authentication = _validate_provider(provider, revision)
    batches: list[RepositoryBatchReceipt] = []
    tombstones: list[RepositoryTombstone] = []
    manifest_files: list[RepositoryManifestFile] = []
    batcher = _RepositoryBatcher(bounds)
    seen_paths: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    pages = 0
    while True:
        page = await provider.fetch_page(
            revision, cursor=cursor, page_size=bounds.provider_page_size
        )
        pages += 1
        if page.revision != revision:
            raise RepositoryTransportError("provider page changed immutable revision")
        next_cursor = page.next_cursor
        if next_cursor is not None and next_cursor in seen_cursors:
            raise RepositoryTransportError("provider pagination cursor repeated")
        _accept_paths(
            page,
            seen_paths=seen_paths,
            tombstones=tombstones,
            manifest_files=manifest_files,
        )
        await _accept_files(
            page,
            batcher=batcher,
            client=client,
            batches=batches,
        )
        if next_cursor is None:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    final_batch = batcher.finish()
    if final_batch:
        batches.append(await submit_repository_batch(client, final_batch))
    return RepositoryIndexReceipt(
        revision=revision,
        authentication=authentication,
        manifest=RepositorySnapshotManifest(
            revision=revision,
            files=tuple(manifest_files),
            tombstones=tuple(tombstones),
        ),
        batches=tuple(batches),
        provider_pages=pages,
    )
