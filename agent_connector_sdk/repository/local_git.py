"""Repository provider over a local Git repository, read through the git CLI.

Refs are full names (``refs/heads/main``) pinned to their peeled commit and
tree; trees list blob entries (submodule commits are not content); blobs are
read by object id, so every read is immutable.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from agent_connector_sdk.repository.errors import RepositoryTransportError
from agent_connector_sdk.repository.models import (
    RepositoryAuthentication,
    RepositoryRevision,
)
from agent_connector_sdk.repository.refs import (
    RepositoryRef,
    RepositoryTreeEntry,
    RepositoryTreePage,
)

__all__ = ["LocalGitRepositoryProvider"]

_DEFAULT_REF_PREFIXES = ("refs/heads", "refs/tags")


class LocalGitRepositoryProvider:
    """``RepositorySnapshotProvider`` for a repository on the local filesystem."""

    name = "local-git"

    def __init__(
        self,
        root: Path,
        *,
        repository_id: str,
        ref_prefixes: tuple[str, ...] = _DEFAULT_REF_PREFIXES,
    ) -> None:
        self.root = root
        self.repository_id = repository_id
        self.ref_prefixes = ref_prefixes
        self.authentication = RepositoryAuthentication(
            provider=self.name,
            principal="local-filesystem",
            mechanism="filesystem",
            credential_reference_digest=hashlib.sha256(
                str(root.resolve()).encode("utf-8")
            ).hexdigest(),
        )
        self._trees: dict[str, tuple[RepositoryTreeEntry, ...]] = {}

    async def _git(self, *args: str) -> bytes:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(self.root),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode("utf-8", "replace").strip()
            raise RepositoryTransportError(f"git {args[0]} failed: {message}")
        return stdout

    async def list_refs(self) -> tuple[RepositoryRef, ...]:
        """Every ref under ``ref_prefixes`` with its peeled commit and tree."""
        listing = await self._git(
            "for-each-ref", "--format=%(refname)", *self.ref_prefixes
        )
        names = listing.decode("utf-8").split()
        if not names:
            return ()
        peeled = [f"{name}^{{{kind}}}" for name in names for kind in ("commit", "tree")]
        ids = (await self._git("rev-parse", *peeled)).decode("ascii").split()
        return tuple(
            RepositoryRef(
                name=name,
                revision=RepositoryRevision(
                    provider=self.name,
                    repository_id=self.repository_id,
                    revision_id=ids[2 * index],
                    tree_id=ids[2 * index + 1],
                ),
            )
            for index, name in enumerate(names)
        )

    async def _tree(
        self, revision: RepositoryRevision
    ) -> tuple[RepositoryTreeEntry, ...]:
        cached = self._trees.get(revision.tree_id)
        if cached is None:
            raw = await self._git(
                "ls-tree", "-r", "-z", "--full-tree", revision.tree_id
            )
            records = (
                item.split("\t", 1) for item in raw.decode("utf-8").split("\0") if item
            )
            cached = tuple(
                RepositoryTreeEntry(path=path, blob_id=meta.split()[2])
                for meta, path in records
                if meta.split()[1] == "blob"
            )
            self._trees[revision.tree_id] = cached
        return cached

    async def list_tree(
        self,
        revision: RepositoryRevision,
        *,
        cursor: str | None,
        page_size: int,
    ) -> RepositoryTreePage:
        """One page of ``revision``'s blob entries; the cursor is an offset."""
        entries = await self._tree(revision)
        start = int(cursor) if cursor is not None else 0
        end = start + page_size
        return RepositoryTreePage(
            revision=revision,
            entries=entries[start:end],
            next_cursor=str(end) if end < len(entries) else None,
        )

    async def fetch_blob(self, revision: RepositoryRevision, blob_id: str) -> bytes:
        """The bytes of blob ``blob_id``."""
        return await self._git("cat-file", "blob", blob_id)
