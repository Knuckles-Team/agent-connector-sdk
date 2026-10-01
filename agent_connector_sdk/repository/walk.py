"""Enumerate a repository's refs and walk each immutable tree without content.

Implements the walk phase of SDK-REPOSITORY-TRANSPORT-R003: refs pinned to the
same immutable tree share one walk, and a provider that can read many tree
objects in one batch (``prime_trees``) is given every distinct tree id up
front, so a large repository with many branches is walked with one call per
distinct Git tree rather than one call per object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.models import RepositoryRevision
from agent_connector_sdk.repository.provider import RepositoryRefWalkProvider
from agent_connector_sdk.repository.refs import RepositoryRef, RepositoryTreeEntry

__all__ = ["RefTree", "walk_refs"]


@dataclass(frozen=True)
class RefTree:
    """One ref and its complete tree listing, sorted by path."""

    ref: RepositoryRef
    entries: tuple[RepositoryTreeEntry, ...]


class _BulkTreeProvider(Protocol):
    async def prime_trees(self, tree_ids: tuple[str, ...]) -> None: ...


def _validate_refs(
    provider: RepositoryRefWalkProvider, refs: tuple[RepositoryRef, ...]
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
    provider: RepositoryRefWalkProvider, revision: RepositoryRevision, page_size: int
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
    provider: RepositoryRefWalkProvider, *, page_size: int
) -> tuple[tuple[RefTree, ...], int]:
    """Return every ref's tree (sorted by ref name) and the pages fetched.

    Refs pinned to the same immutable tree share one tree walk. When the
    provider exposes ``prime_trees``, every distinct tree id across all refs
    (including nested, content-addressed subtrees) is requested through it
    before any individual walk begins, so a provider backed by a batch object
    read (for example ``git cat-file --batch``) issues one such call for the
    whole repository instead of one per branch or tag.
    """
    refs = _validate_refs(provider, await provider.list_refs())
    tree_ids = tuple(dict.fromkeys(item.revision.tree_id for item in refs))
    prime = getattr(provider, "prime_trees", None)
    if callable(prime):
        await cast(_BulkTreeProvider, provider).prime_trees(tree_ids)
    walked: dict[str, tuple[RepositoryTreeEntry, ...]] = {}
    pages = 0
    for item in refs:
        tree_id = item.revision.tree_id
        if tree_id not in walked:
            walked[tree_id], fetched = await _walk_tree(
                provider, item.revision, page_size
            )
            pages += fetched
    trees = tuple(
        RefTree(ref=item, entries=walked[item.revision.tree_id]) for item in refs
    )
    return trees, pages
