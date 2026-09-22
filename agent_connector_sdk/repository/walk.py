"""Enumerate a repository's refs and walk each immutable tree without content."""

from __future__ import annotations

from dataclasses import dataclass

from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.models import RepositoryRevision
from agent_connector_sdk.repository.provider import RepositorySnapshotProvider
from agent_connector_sdk.repository.refs import RepositoryRef, RepositoryTreeEntry

__all__: list[str] = []


@dataclass(frozen=True)
class RefTree:
    """One ref and its complete tree listing, sorted by path."""

    ref: RepositoryRef
    entries: tuple[RepositoryTreeEntry, ...]


def _validate_refs(
    provider: RepositorySnapshotProvider, refs: tuple[RepositoryRef, ...]
) -> tuple[RepositoryRef, ...]:
    if provider.authentication.provider != provider.name:
        raise RepositoryTransportError("provider and authentication disagree")
    ordered = tuple(sorted(refs, key=lambda item: item.name))
    if len({item.name for item in ordered}) != len(ordered):
        raise RepositoryTransportError("provider listed a ref name twice")
    for item in ordered:
        revision = item.revision
        same_source = revision.provider == provider.name
        if not same_source or revision.repository_id != provider.repository_id:
            raise RepositoryTransportError(f"ref {item.name} names another repository")
    return ordered


async def _walk_tree(
    provider: RepositorySnapshotProvider, revision: RepositoryRevision, page_size: int
) -> tuple[tuple[RepositoryTreeEntry, ...], int]:
    entries: dict[str, RepositoryTreeEntry] = {}
    seen_cursors: set[str] = set()
    cursor: str | None = None
    pages = 0
    while True:
        page = await provider.list_tree(revision, cursor=cursor, page_size=page_size)
        pages += 1
        if page.revision != revision:
            raise RepositoryTransportError("provider page changed immutable revision")
        for entry in page.entries:
            if entries.setdefault(entry.path, entry) is not entry:
                raise RepositoryTransportError("provider repeated a repository path")
        cursor = page.next_cursor
        if cursor is None:
            return tuple(entries[path] for path in sorted(entries)), pages
        if cursor in seen_cursors:
            raise RepositoryTransportError("provider pagination cursor repeated")
        seen_cursors.add(cursor)


async def walk_refs(
    provider: RepositorySnapshotProvider, *, page_size: int
) -> tuple[tuple[RefTree, ...], int]:
    """Return every ref's tree (sorted by ref name) and the pages fetched.

    Refs pinned to the same revision share one tree walk.
    """
    refs = _validate_refs(provider, await provider.list_refs())
    walked: dict[RepositoryRevision, tuple[RepositoryTreeEntry, ...]] = {}
    pages = 0
    for item in refs:
        if item.revision not in walked:
            walked[item.revision], fetched = await _walk_tree(
                provider, item.revision, page_size
            )
            pages += fetched
    trees = tuple(RefTree(ref=item, entries=walked[item.revision]) for item in refs)
    return trees, pages
