"""Document sources: filesystem and git-markdown corpora with governed ingest.

A document source reads text files and turns them into
:class:`~agent_connector_sdk.ingest.model.Document` observations. It owns no
cursor: :func:`ingest_documents` reads the provider cursor from the stream's
durable epistemic-graph checkpoint, polls the source after it, applies the
permission envelope to every document, and commits one
:class:`~agent_connector_sdk.ingest.model.ChangeSet` through
:class:`~agent_connector_sdk.ingest.service.KnowledgeIngest`. Chunking and
embedding happen inside epistemic-graph after the commit, so every document
carries its access facts before it can be embedded.

Persisted identity is portable: record ids and source references are derived
from a hashed namespace and the relative path, never from a local root. A
source reference carries its revision as ``?rev=<revision>``; evidence
digests are bare 64-character SHA-256 hex.
"""

from __future__ import annotations

import asyncio
import dataclasses
import fnmatch
import hashlib
import subprocess  # nosec B404 - fixed git argv, no shell
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import yaml
from epistemic_graph.generated.source_ingestion import SourceIngestionReceipt

from agent_connector_sdk.contracts import ExternalAccess, default_external_access
from agent_connector_sdk.ingest.model import (
    ChangeSet,
    Document,
    IngestBinding,
    Withdrawal,
)
from agent_connector_sdk.ingest.service import KnowledgeIngest

__all__ = [
    "DEFAULT_TEXT_EXTENSIONS",
    "DocumentBatch",
    "DocumentGovernance",
    "DocumentIngestReport",
    "DocumentSource",
    "DomainPack",
    "FilesystemDocumentSource",
    "GitMarkdownDocumentSource",
    "GovernanceRefusedError",
    "access_properties",
    "apply_access",
    "ingest_documents",
]

#: Text formats a filesystem source reads when no extensions are configured.
DEFAULT_TEXT_EXTENSIONS = frozenset({".md", ".markdown", ".txt", ".rst"})
_MAX_FILE_BYTES = 8 * 1024 * 1024
_GIT_TIMEOUT_S = 60.0


def _digest(material: str | bytes) -> str:
    data = material.encode("utf-8") if isinstance(material, str) else material
    return hashlib.sha256(data).hexdigest()


def _namespace(source_id: str, fallback: str) -> str:
    return _digest(source_id or fallback)[:16]


def _read_roles(access: ExternalAccess) -> list[str]:
    roles = [f"group:{group}" for group in access.group_ids if group]
    roles += [f"user:{email}" for email in access.user_emails if email]
    roles += [str(role).strip() for role in access.read_roles if str(role).strip()]
    return list(dict.fromkeys(roles))


def access_properties(access: ExternalAccess) -> dict[str, Any]:
    """The record properties that carry one source ACL into epistemic-graph.

    Groups become ``group:<id>`` and users ``user:<email>`` read roles beside
    the provider-neutral roles; markings stay mandatory compartments.
    """
    return {
        "access_public": access.is_public,
        "access_read_roles": _read_roles(access),
        "access_markings": [marking for marking in access.markings if marking],
    }


def apply_access(document: Document, access: ExternalAccess) -> Document:
    """``document`` with ``access`` stamped onto its properties."""
    return dataclasses.replace(
        document, properties={**document.properties, **access_properties(access)}
    )


@dataclass(frozen=True)
class DocumentBatch:
    """One poll: documents to upsert, removals, and the cursor after them."""

    documents: tuple[Document, ...] = ()
    withdrawals: tuple[Withdrawal, ...] = ()
    cursor: str | None = None


class DocumentSource(Protocol):
    """A source that polls documents after a provider cursor."""

    kind: str

    def poll(self, cursor: str | None) -> DocumentBatch:
        """Documents changed after ``cursor`` (``None`` reads everything)."""
        ...


class GovernanceRefusedError(Exception):
    """The permission envelope refused one document."""


#: Resolves the permission envelope for one document or raises
#: :class:`GovernanceRefusedError`.
DocumentGovernance = Callable[[Document], ExternalAccess]


def _iso(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1e9, tz=UTC).isoformat()


class FilesystemDocumentSource:
    """Text files under one authorized root, polled by modification time.

    The cursor is the largest ``st_mtime_ns`` already accepted, so a re-poll
    over an unchanged tree returns no documents. Symlinks and paths resolving
    outside the root are never read.
    """

    kind = "filesystem"

    def __init__(
        self,
        root: str | Path,
        *,
        extensions: frozenset[str] = DEFAULT_TEXT_EXTENSIONS,
        recursive: bool = True,
        access: ExternalAccess | None = None,
        source_id: str = "",
        doc_type: str = "",
    ) -> None:
        self._root = Path(root).expanduser().resolve(strict=False)
        self._extensions = frozenset(ext.lower() for ext in extensions)
        self._recursive = recursive
        self._access = access or default_external_access()
        self._namespace = _namespace(source_id, str(self._root))
        self._doc_type = doc_type

    def _files(self) -> Iterator[Path]:
        if not self._root.is_dir():
            return
        walker = self._root.rglob("*") if self._recursive else self._root.glob("*")
        for path in sorted(walker):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(self._root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.suffix.lower() not in self._extensions:
                continue
            if not path.resolve(strict=True).is_relative_to(self._root):
                continue
            yield path

    def _document(self, path: Path) -> Document | None:
        stat = path.stat()
        if stat.st_size > _MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        if not text.strip():
            return None
        relpath = path.relative_to(self._root).as_posix()
        uri = f"filesystem://{self._namespace}/{quote(relpath, safe='/')}"
        properties: dict[str, Any] = {
            "relpath": relpath,
            "doc_type": self._doc_type or path.suffix.lstrip(".").lower(),
            "size_bytes": stat.st_size,
            "evidence_digest": _digest(data),
        }
        return apply_access(
            Document(
                id=f"filesystem:{_digest(self._namespace + '/' + relpath)}",
                text=text,
                title=path.name,
                source_uri=f"{uri}?rev={stat.st_mtime_ns}",
                properties=properties,
                updated_at=_iso(stat.st_mtime_ns),
            ),
            self._access,
        )

    def poll(self, cursor: str | None) -> DocumentBatch:
        """Files modified after ``cursor``; the cursor advances to their max mtime."""
        prior = int(cursor) if cursor else -1
        newest = prior
        documents = []
        for path in self._files():
            mtime = path.stat().st_mtime_ns
            if mtime <= prior:
                continue
            document = self._document(path)
            if document is not None:
                documents.append(document)
                newest = max(newest, mtime)
        return DocumentBatch(
            documents=tuple(documents),
            cursor=str(newest) if newest >= 0 else cursor,
        )


@dataclass(frozen=True)
class DomainPack:
    """One markdown corpus inside a git repository.

    Attributes:
        name: The corpus name recorded on every document (``corpus``).
        globs: Repository-relative ``fnmatch`` patterns selecting its files.
        doc_type: The document type recorded on every document.
    """

    name: str
    globs: tuple[str, ...]
    doc_type: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.globs or not self.doc_type.strip():
            raise ValueError("a domain pack needs a name, globs and a doc_type")

    def selects(self, relpath: str) -> bool:
        """Whether ``relpath`` belongs to this pack."""
        return any(fnmatch.fnmatchcase(relpath, pattern) for pattern in self.globs)


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    try:
        loaded = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _concept_ids(front: dict[str, Any]) -> str | None:
    value = front.get("concepts", front.get("concept_ids"))
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return None
    ids = [str(item).strip() for item in value if str(item).strip()]
    # epistemic-graph types documentation conceptIds as one xsd:string.
    return " ".join(ids) or None


class GitMarkdownDocumentSource:
    """A domain pack read from a git repository at its ``HEAD`` revision.

    The cursor is the last accepted commit. A poll after it reads only the
    files the diff touched; deletions become withdrawals. Content is read from
    the revision itself, not the working tree, so lineage names exactly the
    bytes ingested.
    """

    kind = "git_markdown"

    def __init__(
        self,
        root: str | Path,
        pack: DomainPack,
        *,
        access: ExternalAccess | None = None,
        source_id: str = "",
    ) -> None:
        self._root = Path(root).expanduser().resolve(strict=False)
        self._pack = pack
        self._access = access or default_external_access()
        self._namespace = _namespace(source_id, str(self._root))

    def _git(self, *args: str) -> bytes:
        return subprocess.run(  # nosec B603 - fixed git argv
            ["git", "-C", str(self._root), *args],
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
            check=True,
        ).stdout

    def _known(self, revision: str) -> bool:
        try:
            self._git("cat-file", "-e", f"{revision}^{{commit}}")
        except subprocess.CalledProcessError:
            return False
        return True

    def _changes(self, cursor: str | None, head: str) -> tuple[list[str], list[str]]:
        if cursor is None or not self._known(cursor):
            listed = self._git("ls-tree", "-r", "-z", "--name-only", head)
            return [p for p in listed.decode().split("\0") if p], []
        raw = self._git("diff", "--name-status", "--no-renames", "-z", cursor, head)
        fields = [field for field in raw.decode().split("\0") if field]
        changed: list[str] = []
        deleted: list[str] = []
        for status, path in zip(fields[::2], fields[1::2], strict=True):
            (deleted if status == "D" else changed).append(path)
        return changed, deleted

    def _record_id(self, relpath: str) -> str:
        return (
            f"git-markdown:{_digest(f'{self._namespace}/{self._pack.name}/{relpath}')}"
        )

    def _document(self, head: str, relpath: str) -> Document | None:
        data = self._git("show", f"{head}:{relpath}")
        if len(data) > _MAX_FILE_BYTES:
            return None
        text = data.decode("utf-8", errors="replace")
        if not text.strip():
            return None
        front = _frontmatter(text)
        properties: dict[str, Any] = {
            "corpus": self._pack.name,
            "relpath": relpath,
            "git_commit": head,
            "doc_type": self._pack.doc_type,
            "evidence_digest": _digest(data),
            "conceptIds": _concept_ids(front),
        }
        uri = f"git-markdown://{self._namespace}/{quote(relpath, safe='/')}"
        title = front.get("name") or front.get("title") or Path(relpath).name
        return apply_access(
            Document(
                id=self._record_id(relpath),
                text=text,
                title=str(title),
                source_uri=f"{uri}?rev={head}",
                properties=properties,
            ),
            self._access,
        )

    def poll(self, cursor: str | None) -> DocumentBatch:
        """Pack files changed after commit ``cursor``, read at ``HEAD``."""
        head = self._git("rev-parse", "HEAD").decode().strip()
        if cursor == head:
            return DocumentBatch(cursor=head)
        changed, deleted = self._changes(cursor, head)
        documents = [
            document
            for relpath in sorted(changed)
            if self._pack.selects(relpath)
            and (document := self._document(head, relpath)) is not None
        ]
        withdrawals = [
            Withdrawal(self._record_id(relpath), f"deleted at {head}")
            for relpath in sorted(deleted)
            if self._pack.selects(relpath)
        ]
        return DocumentBatch(tuple(documents), tuple(withdrawals), head)


@dataclass(frozen=True)
class DocumentIngestReport:
    """What one :func:`ingest_documents` run committed or refused."""

    documents: int
    documents_failed: int
    withdrawn: int
    cursor_advanced: bool
    failures: tuple[str, ...] = ()
    receipt: SourceIngestionReceipt | None = None


def _govern(
    documents: tuple[Document, ...], governance: DocumentGovernance | None
) -> tuple[list[Document], list[str]]:
    if governance is None:
        return list(documents), []
    admitted, failures = [], []
    for document in documents:
        try:
            admitted.append(apply_access(document, governance(document)))
        except GovernanceRefusedError:
            failures.append(document.id)
    return admitted, failures


async def ingest_documents(
    ingest: KnowledgeIngest,
    binding: IngestBinding,
    source: DocumentSource,
    *,
    governance: DocumentGovernance | None = None,
) -> DocumentIngestReport:
    """Poll ``source`` after the durable cursor and commit one governed change set.

    ``governance`` resolves each document's permission envelope before it is
    submitted. A refused document is not submitted and the cursor does not
    advance, so it is polled again; documents admitted beside it still commit.
    """
    previous = await ingest.accepted_cursor(binding)
    batch = await asyncio.to_thread(source.poll, previous)
    admitted, failures = _govern(batch.documents, governance)
    cursor = previous if failures else batch.cursor
    advanced = cursor != previous
    if not admitted and not batch.withdrawals and not advanced:
        return DocumentIngestReport(0, len(failures), 0, False, tuple(failures))
    receipt = await ingest.submit(
        binding,
        ChangeSet(
            documents=tuple(admitted),
            withdrawals=batch.withdrawals,
            cursor=cursor,
        ),
    )
    return DocumentIngestReport(
        documents=len(admitted),
        documents_failed=len(failures),
        withdrawn=len(batch.withdrawals),
        cursor_advanced=advanced,
        failures=tuple(failures),
        receipt=receipt,
    )
