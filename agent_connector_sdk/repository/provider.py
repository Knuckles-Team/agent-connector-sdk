"""Provider ports for authenticated, immutable repository snapshots."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.repository.models import (
    RepositoryAuthentication,
    RepositoryPage,
    RepositoryRevision,
)
from agent_connector_sdk.repository.refs import RepositoryRef, RepositoryTreePage

__all__ = ["RepositoryRefWalkProvider", "RepositorySnapshotProvider"]


@runtime_checkable
class RepositorySnapshotProvider(Protocol):
    """Fetch pages from one already-authenticated provider session.

    Vendor clients remain connector-owned. The SDK requires their provider port
    to expose non-secret authentication evidence and to fetch by immutable
    revision, never by a mutable branch name.
    """

    name: str
    authentication: RepositoryAuthentication

    async def fetch_page(
        self,
        revision: RepositoryRevision,
        *,
        cursor: str | None,
        page_size: int,
    ) -> RepositoryPage:
        """Return one bounded page for exactly ``revision``."""
        ...


@runtime_checkable
class RepositoryRefWalkProvider(Protocol):
    """List refs and walk each immutable tree's paths and blob ids, no content.

    This is the walk phase a connector-owned provider implements so the SDK can
    traverse a repository's refs, visiting each distinct Git tree only once and
    reading objects in batches rather than one call per object
    (SDK-REPOSITORY-TRANSPORT-R003).
    """

    name: str
    repository_id: str
    authentication: RepositoryAuthentication

    async def list_refs(self) -> tuple[RepositoryRef, ...]:
        """Return every ref of this repository, pinned to an immutable revision."""
        ...

    async def list_tree(
        self,
        revision: RepositoryRevision,
        *,
        cursor: str | None,
        page_size: int,
    ) -> RepositoryTreePage:
        """Return one bounded page of ``revision``'s tree, without blob content."""
        ...
