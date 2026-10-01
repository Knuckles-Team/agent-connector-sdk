"""Provider port for the repository walk phase (ref enumeration, no content)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_connector_sdk.repository.models import (
    RepositoryAuthentication,
    RepositoryRevision,
)
from agent_connector_sdk.repository.refs import RepositoryRef, RepositoryTreePage

__all__ = ["RepositoryRefWalkProvider"]


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
