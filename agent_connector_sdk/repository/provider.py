"""Provider port for authenticated, immutable, branch-aware repository reads."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.repository.models import (
    RepositoryAuthentication,
    RepositoryRevision,
)
from agent_connector_sdk.repository.refs import RepositoryRef, RepositoryTreePage

__all__ = ["RepositorySnapshotProvider"]


@runtime_checkable
class RepositorySnapshotProvider(Protocol):
    """Read one repository through an already-authenticated provider session.

    Vendor clients remain connector-owned. The SDK requires their provider port
    to expose non-secret authentication evidence, to enumerate refs pinned to
    immutable revisions, to page trees without content, and to fetch blob bytes
    by immutable Git object id, never by a mutable branch name.
    """

    name: str
    repository_id: str
    authentication: RepositoryAuthentication

    async def list_refs(self) -> tuple[RepositoryRef, ...]:
        """Return every ref to index, each pinned to an immutable revision."""
        ...

    async def list_tree(
        self,
        revision: RepositoryRevision,
        *,
        cursor: str | None,
        page_size: int,
    ) -> RepositoryTreePage:
        """Return one bounded page of file entries for exactly ``revision``."""
        ...

    async def fetch_blob(self, revision: RepositoryRevision, blob_id: str) -> bytes:
        """Return the bytes of Git blob ``blob_id`` reachable from ``revision``."""
        ...
