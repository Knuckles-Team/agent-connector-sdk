"""Repository ref-walk provider over a local Git repository, via the git CLI.

Refs are full names (``refs/heads/main``) pinned to their peeled commit and
tree; trees list blob entries (submodule commits are not content). This is the
reference implementation of ``RepositoryRefWalkProvider``, used by the SDK's
own tests and available to a connector that hydrates from a local checkout.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
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
    """``RepositoryRefWalkProvider`` for a repository on the local filesystem."""

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

    async def prime_trees(self, tree_ids: tuple[str, ...]) -> None:
        """Read all distinct root trees through one Git batch process.

        Tree objects are content addressed, so common subtrees are read once
        even when many branch tips have different root trees
        (SDK-REPOSITORY-TRANSPORT-R003).
        """
        roots = tuple(dict.fromkeys(oid for oid in tree_ids if oid not in self._trees))
        if not roots:
            return
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(self.root),
            "cat-file",
            "--batch",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdin is None or process.stdout is None:
            raise RepositoryTransportError("git cat-file did not open its pipes")
        objects: dict[str, tuple[tuple[bytes, str, str], ...]] = {}
        pending = deque(roots)
        requested: set[str] = set()
        try:
            while pending:
                oid = pending.popleft()
                if oid in requested:
                    continue
                requested.add(oid)
                process.stdin.write(f"{oid}\n".encode("ascii"))
                await process.stdin.drain()
                header = (await process.stdout.readline()).split()
                if (
                    len(header) != 3
                    or header[0].decode("ascii") != oid
                    or header[1] != b"tree"
                ):
                    raise RepositoryTransportError(
                        f"git cat-file did not return tree {oid}"
                    )
                size = int(header[2])
                raw = await process.stdout.readexactly(size + 1)
                if raw[-1:] != b"\n":
                    raise RepositoryTransportError(
                        "git cat-file returned malformed tree framing"
                    )
                record_size = len(bytes.fromhex(oid))
                records: list[tuple[bytes, str, str]] = []
                payload = raw[:-1]
                offset = 0
                while offset < len(payload):
                    boundary = payload.find(b"\0", offset)
                    if boundary < 0 or boundary + 1 + record_size > len(payload):
                        raise RepositoryTransportError(
                            "git cat-file returned malformed tree"
                        )
                    mode_name = payload[offset:boundary]
                    object_id = payload[boundary + 1 : boundary + 1 + record_size]
                    offset = boundary + 1 + record_size
                    mode, name_bytes = mode_name.split(b" ", 1)
                    child = object_id.hex()
                    records.append((mode, name_bytes.decode("utf-8"), child))
                    if mode == b"40000" and child not in requested:
                        pending.append(child)
                objects[oid] = tuple(records)
        finally:
            process.stdin.close()
            await process.stdin.wait_closed()
            await process.wait()
        if process.returncode != 0:
            if process.stderr is None:
                raise RepositoryTransportError("git cat-file failed with no stderr pipe")
            message = (await process.stderr.read()).decode("utf-8", "replace").strip()
            raise RepositoryTransportError(f"git cat-file failed: {message}")
        for root in roots:
            entries: list[RepositoryTreeEntry] = []
            stack = [(root, "")]
            while stack:
                oid, prefix = stack.pop()
                for mode, name, child in objects[oid]:
                    path = f"{prefix}{name}"
                    if mode == b"40000":
                        stack.append((child, f"{path}/"))
                    elif mode in (b"100644", b"100755", b"120000"):
                        entries.append(RepositoryTreeEntry(path=path, blob_id=child))
            self._trees[root] = tuple(sorted(entries, key=lambda item: item.path))

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
