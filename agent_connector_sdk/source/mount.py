"""Sparse virtual workspace over the source client (overlay copy-up backend).

Files materialize lazily on read through the client's blob path. Writes are
recorded as a pending changeset and never mutate the mounted revision. No
clone, object database or full checkout is kept. A FUSE backend may sit in
front of the same operations on hosts that provide one.
"""

from __future__ import annotations

import base64
import hashlib
import json
import posixpath
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_connector_sdk.source.client import (
    BlobRequest,
    ChangeEntry,
    CommitRequest,
    SourceClient,
    SourceRefusedError,
    TreeEntry,
    TreeRequest,
)

__all__ = [
    "MountEntry",
    "MountRefusedError",
    "MountState",
    "PendingEntry",
    "SourceMount",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class MountEntry(_Model):
    path: str
    mode: str
    digest: str


class PendingEntry(_Model):
    path: str
    operation: Literal["put", "delete"]
    blob_ref: str | None = None


class MountState(_Model):
    repository_id: str
    base_revision: str
    prefixes: tuple[str, ...] = Field(min_length=1)
    pending_changeset_id: str | None = None


class MountRefusedError(RuntimeError):
    """The mount refused to start, read or write; ``reason`` is a stable code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _clean(path: str) -> str:
    pure = PurePosixPath(path)
    if (
        not path
        or pure.is_absolute()
        or "\\" in path
        or any(part in ("", ".", "..") for part in path.split("/"))
        or posixpath.normpath(path) != path
    ):
        raise MountRefusedError("path_denied")
    return path


class SourceMount:
    """One mounted workspace: declared prefixes only, pending changeset in memory."""

    def __init__(
        self,
        client: SourceClient,
        *,
        root: Path,
        repository_id: str,
        ref: str,
        branch: str,
        prefixes: tuple[str, ...],
        base_revision: str,
    ) -> None:
        self._client = client
        self._root = root.resolve()
        self._repository, self._ref, self._branch = repository_id, ref, branch
        self._prefixes = prefixes
        self._base = base_revision
        self._pending: dict[str, PendingEntry] = {}
        self._pending_bytes: dict[str, bytes] = {}
        self._listed: dict[str, TreeEntry] = {}
        self.reads = 0
        self.cache_hits = 0
        self.events: list[dict[str, Any]] = []

    @classmethod
    async def start(
        cls,
        client: Any,
        *,
        root: Path,
        repository_id: str,
        ref: str,
        branch: str,
        prefixes: tuple[str, ...],
    ) -> SourceMount:
        if not isinstance(client, SourceClient):
            raise MountRefusedError("client_not_admitted")
        if not prefixes:
            raise MountRefusedError("unknown_prefix")
        cleaned = tuple(_clean(prefix.rstrip("/")) for prefix in prefixes)
        revisions: set[str] = set()
        for prefix in cleaned:
            try:
                page = await client.tree(
                    TreeRequest(
                        repository_id=repository_id,
                        ref=ref,
                        path_prefix=prefix,
                        page_size=1,
                    )
                )
            except SourceRefusedError as error:
                raise MountRefusedError(
                    "unknown_prefix" if error.reason == "not_found" else error.reason
                ) from None
            revisions.add(page.provenance.revision)
        if len(revisions) != 1:
            raise MountRefusedError("conflict")
        root.mkdir(parents=True, exist_ok=True)
        mount = cls(
            client,
            root=root,
            repository_id=repository_id,
            ref=ref,
            branch=branch,
            prefixes=cleaned,
            base_revision=revisions.pop(),
        )
        mount._event("mount")
        return mount

    @property
    def state(self) -> MountState:
        return MountState(
            repository_id=self._repository,
            base_revision=self._base,
            prefixes=self._prefixes,
            pending_changeset_id=self._digest() if self._pending else None,
        )

    @property
    def pending(self) -> tuple[PendingEntry, ...]:
        return tuple(self._pending[path] for path in sorted(self._pending))

    async def listdir(self, directory: str) -> tuple[MountEntry, ...]:
        """Resolve one directory lazily from the served tree operation."""
        directory = _clean(directory.rstrip("/"))
        self._require_declared(directory)
        entries: list[TreeEntry] = []
        continuation: str | None = None
        while True:
            page = await self._client.tree(
                TreeRequest(
                    repository_id=self._repository,
                    ref=self._base,
                    path_prefix=directory,
                    continuation=continuation,
                )
            )
            entries.extend(page.entries)
            continuation = page.continuation
            if continuation is None:
                break
        for entry in entries:
            self._listed[entry.path] = entry
        found = {
            e.path: MountEntry(path=e.path, mode=e.mode, digest=e.digest)
            for e in entries
        }
        for path, change in self._pending.items():
            if change.operation == "put" and path.startswith(directory + "/"):
                found[path] = MountEntry(
                    path=path, mode="100644", digest=str(change.blob_ref)
                )
            elif change.operation == "delete":
                found.pop(path, None)
        return tuple(found[path] for path in sorted(found))

    async def read(self, path: str) -> bytes:
        """Materialize a file (copy-up) and return its bytes."""
        path = self._checked(path)
        self.reads += 1
        pending = self._pending.get(path)
        if pending is not None:
            if pending.operation == "delete":
                raise MountRefusedError("not_found")
            return self._pending_bytes[path]
        entry = self._listed.get(path)
        if entry is None:
            await self.listdir(posixpath.dirname(path) or path.split("/")[0])
            entry = self._listed.get(path)
        if entry is None:
            raise MountRefusedError("not_found")
        page = await self._client.blob(
            BlobRequest(
                repository_id=self._repository,
                ref=self._base,
                path=path,
                digest=entry.digest,
            )
        )
        if page.cache == "hit":
            self.cache_hits += 1
        self._materialize(path, page.content)
        return page.content

    def write(self, path: str, data: bytes) -> None:
        """Record a write; a repeated write to one path replaces the earlier entry."""
        path = self._checked(path)
        blob_ref = hashlib.sha256(data).hexdigest()
        self._materialize(path, data)
        self._pending[path] = PendingEntry(
            path=path, operation="put", blob_ref=blob_ref
        )
        self._pending_bytes[path] = data

    def delete(self, path: str) -> None:
        path = self._checked(path)
        self._pending[path] = PendingEntry(path=path, operation="delete")
        self._pending_bytes.pop(path, None)

    async def flush(self) -> Any:
        """Submit the pending changeset as one commit; keep it intact on failure."""
        if not self._pending:
            raise MountRefusedError("nothing_to_flush")
        changeset = self._digest()
        changes = tuple(
            ChangeEntry(
                path=item.path,
                operation=item.operation,
                blob_digest=item.blob_ref,
                content_base64=base64.b64encode(self._pending_bytes[item.path]).decode()
                if item.operation == "put"
                else None,
            )
            for item in self.pending
        )
        try:
            receipt = await self._client.commit(
                CommitRequest(
                    repository_id=self._repository,
                    branch=self._branch,
                    base_revision=self._base,
                    message=f"workspace flush {changeset[:12]}",
                    changes=changes,
                    change_id=changeset[:32],
                )
            )
        except SourceRefusedError as error:
            self._event("flush_refused", reason=error.reason)
            raise
        outcomes = [item.model_dump() for item in receipt.outcomes]
        self._event(
            "flush",
            changeset=changeset,
            receipt=receipt.provenance.receipt_ref,
            revision=receipt.revision,
            outcomes=outcomes,
        )
        self._pending.clear()
        self._pending_bytes.clear()
        self._base = receipt.revision
        self._listed.clear()
        return receipt

    def _require_declared(self, path: str) -> None:
        if not any(path == p or path.startswith(p + "/") for p in self._prefixes):
            raise MountRefusedError("path_denied")

    def _checked(self, path: str) -> str:
        path = _clean(path)
        self._require_declared(path)
        return path

    def _materialize(self, path: str, data: bytes) -> None:
        target = self._root.joinpath(*path.split("/"))
        walker = self._root
        for part in path.split("/"):
            walker = walker / part
            if walker.is_symlink():
                raise MountRefusedError("path_denied")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.parent.resolve().is_relative_to(self._root):
                raise MountRefusedError("path_denied")
        except OSError:
            raise MountRefusedError("path_denied") from None
        target.write_bytes(data)

    def _digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                [item.model_dump() for item in self.pending],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def _event(self, name: str, **extra: Any) -> None:
        self.events.append(
            {
                "event": name,
                "repository_id": self._repository,
                "base_revision": self._base,
                "prefixes": list(self._prefixes),
                "reads": self.reads,
                "cache_hits": self.cache_hits,
                "pending_changeset": self._digest() if self._pending else None,
                **extra,
            }
        )
