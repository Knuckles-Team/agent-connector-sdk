"""Provider port for authenticated, immutable repository snapshots."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.repository.models import (
    RepositoryAuthentication,
    RepositoryPage,
    RepositoryRevision,
)

__all__ = ["RepositorySnapshotProvider"]


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
