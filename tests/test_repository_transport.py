"""The repository transport batches source bytes and preserves native outcomes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

import pytest
from epistemic_graph.client import EpistemicGraphClient

from agent_connector_sdk.repository import (
    RepositoryAuthentication,
    RepositoryBatchLimits,
    RepositoryBatchReceipt,
    RepositoryFile,
    RepositoryIndexReceipt,
    RepositoryPage,
    RepositoryRevision,
    RepositorySnapshotProvider,
    RepositoryTombstone,
    RepositoryTransportError,
    index_repository_snapshot,
)


def _digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _file(path: str, content: bytes) -> RepositoryFile:
    return RepositoryFile(path=path, blob_digest=_digest(content), content=content)


def _revision(tree: str = "b") -> RepositoryRevision:
    return RepositoryRevision(
        provider="git-forge",
        repository_id="team/project",
        revision_id="a" * 40,
        tree_id=tree * 40,
    )


class _Status(StrEnum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


@dataclass
class _Outcome:
    file_path: str
    status: _Status
    content_digest: str
    parser_capability_digest: str = f"sha256:{'c' * 64}"
    diagnostics: list[object] = field(default_factory=list)


@dataclass
class _Result:
    file_outcomes: list[_Outcome]
    nodes: list[dict[str, str]]


class _Graph:
    def __init__(self, statuses: dict[str, _Status] | None = None) -> None:
        self.calls: list[list[tuple[str, bytes]]] = []
        self.statuses = statuses or {}
        self.results: list[_Result] = []

    async def index_repository(self, files: list[tuple[str, bytes]]) -> _Result:
        self.calls.append(files)
        outcomes = [
            _Outcome(path, self.statuses.get(path, _Status.SUCCESS), _digest(content))
            for path, content in files
        ]
        result = _Result(outcomes, [{"native": "engine-owned"}])
        self.results.append(result)
        return result


@dataclass
class _Client:
    graph: object


def _client(graph: object) -> EpistemicGraphClient:
    return cast(EpistemicGraphClient, _Client(graph))


class _Provider:
    name = "git-forge"
    authentication = RepositoryAuthentication(
        provider=name,
        principal="service:repository-reader",
        mechanism="bearer",
        credential_reference_digest=f"sha256:{'d' * 64}",
    )

    def __init__(self, pages: list[RepositoryPage]) -> None:
        self.pages = pages
        self.calls: list[tuple[RepositoryRevision, str | None, int]] = []

    async def fetch_page(
        self,
        revision: RepositoryRevision,
        *,
        cursor: str | None,
        page_size: int,
    ) -> RepositoryPage:
        self.calls.append((revision, cursor, page_size))
        return self.pages[len(self.calls) - 1]


@pytest.mark.asyncio
async def test_pages_are_combined_into_one_native_repository_batch() -> None:
    revision = _revision()
    provider = _Provider(
        [
            RepositoryPage(
                revision=revision,
                files=(_file("a.py", b"a = 1\n"),),
                next_cursor="page:2",
            ),
            RepositoryPage(
                revision=revision,
                files=(_file("b.rs", b"fn b() {}\n"),),
            ),
        ]
    )
    graph = _Graph()

    receipt = await index_repository_snapshot(provider, _client(graph), revision)

    assert isinstance(provider, RepositorySnapshotProvider)
    assert isinstance(receipt, RepositoryIndexReceipt)
    assert isinstance(receipt.batches[0], RepositoryBatchReceipt)
    assert graph.calls == [[("a.py", b"a = 1\n"), ("b.rs", b"fn b() {}\n")]]
    assert [call[1] for call in provider.calls] == [None, "page:2"]
    assert receipt.provider_pages == 2
    assert receipt.batches[0].result is graph.results[0]
    assert graph.results[0].nodes == [{"native": "engine-owned"}]


@pytest.mark.asyncio
async def test_typed_outcomes_tombstones_and_revision_metadata_are_preserved() -> None:
    revision = _revision()
    deleted = RepositoryTombstone(
        path="removed.py", prior_blob_digest=f"sha256:{'e' * 64}"
    )
    files = (
        _file("good.py", b"ok"),
        _file("notes.txt", b"plain"),
        _file("broken.py", b"bad"),
    )
    provider = _Provider(
        [RepositoryPage(revision=revision, files=files, tombstones=(deleted,))]
    )
    graph = _Graph({"notes.txt": _Status.UNSUPPORTED, "broken.py": _Status.ERROR})

    receipt = await index_repository_snapshot(provider, _client(graph), revision)

    outcomes = receipt.batches[0].result.file_outcomes
    assert [outcome.status for outcome in outcomes] == list(_Status)
    assert receipt.revision == revision
    assert receipt.authentication == provider.authentication
    assert receipt.manifest.tombstones == (deleted,)
    assert [item.path for item in receipt.manifest.files] == [
        "broken.py",
        "good.py",
        "notes.txt",
    ]
    assert receipt.manifest.fingerprint.startswith("sha256:")


@pytest.mark.asyncio
async def test_batch_limits_create_one_call_per_bounded_batch() -> None:
    revision = _revision()
    files = tuple(_file(f"{index}.py", b"xx") for index in range(3))
    provider = _Provider([RepositoryPage(revision=revision, files=files)])
    graph = _Graph()
    limits = RepositoryBatchLimits(
        max_files=2, max_bytes=4, max_file_bytes=2, provider_page_size=7
    )

    await index_repository_snapshot(provider, _client(graph), revision, limits=limits)

    assert [[path for path, _ in call] for call in graph.calls] == [
        ["0.py", "1.py"],
        ["2.py"],
    ]
    assert provider.calls[0][2] == 7


@pytest.mark.asyncio
async def test_oversized_file_fails_before_engine_call() -> None:
    revision = _revision()
    provider = _Provider(
        [RepositoryPage(revision=revision, files=(_file("large.py", b"xxx"),))]
    )
    graph = _Graph()
    limits = RepositoryBatchLimits(
        max_files=2, max_bytes=2, max_file_bytes=2, provider_page_size=7
    )

    with pytest.raises(RepositoryTransportError, match=r"large\.py"):
        await index_repository_snapshot(
            provider, _client(graph), revision, limits=limits
        )

    assert graph.calls == []


@pytest.mark.asyncio
async def test_revision_drift_fails_before_engine_call() -> None:
    requested = _revision()
    provider = _Provider([RepositoryPage(revision=_revision("f"))])
    graph = _Graph()

    with pytest.raises(RepositoryTransportError, match="changed immutable revision"):
        await index_repository_snapshot(provider, _client(graph), requested)

    assert graph.calls == []


@pytest.mark.asyncio
async def test_repeated_provider_cursor_fails_before_cyclic_page_effects() -> None:
    revision = _revision()
    provider = _Provider(
        [
            RepositoryPage(
                revision=revision,
                files=(_file("a.py", b"a"),),
                next_cursor="repeat",
            ),
            RepositoryPage(
                revision=revision,
                files=(_file("b.py", b"b"),),
                next_cursor="repeat",
            ),
        ]
    )
    graph = _Graph()

    with pytest.raises(RepositoryTransportError, match="cursor repeated"):
        await index_repository_snapshot(provider, _client(graph), revision)

    assert graph.calls == []


@pytest.mark.asyncio
async def test_missing_per_file_outcomes_fail_closed() -> None:
    revision = _revision()
    provider = _Provider(
        [RepositoryPage(revision=revision, files=(_file("a.py", b"a"),))]
    )

    class _OldGraph:
        async def index_repository(self, files: list[tuple[str, bytes]]) -> object:
            return {"files_parsed": len(files)}

    with pytest.raises(RepositoryTransportError, match="lacks typed file_outcomes"):
        await index_repository_snapshot(provider, _client(_OldGraph()), revision)
