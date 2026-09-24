"""Branch-aware transport over a synthetic multi-branch Git repository.

``main`` and ``feature`` share ``pkg/util.py`` byte for byte, ``feature``
changes ``pkg/app.py`` and adds ``pkg/new.py``, and tag ``v1`` pins ``main``.
Every unique blob must be fetched and submitted exactly once while every ref
keeps exactly its own ``(path, blob)`` memberships.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from epistemic_graph.client import EpistemicGraphClient
from epistemic_graph.generated.index_repository import (
    IndexRepositoryScope,
    IndexResult,
)

from agent_connector_sdk.repository import (
    LocalGitRepositoryProvider,
    RepositoryBatchLimits,
    RepositoryBatchReceipt,
    RepositoryIndexManifest,
    RepositoryIndexReceipt,
    RepositoryRefManifest,
    RepositorySnapshotProvider,
    RepositoryTransportError,
    index_repository,
)
from agent_connector_sdk.repository.models import RepositoryRevision

_UTIL = b"def shared():\n    return 1\n"
_APP = b"from pkg.util import shared\n\ndef run():\n    return shared()\n"
_APP_FEATURE = _APP + b"\ndef extra():\n    return 2\n"
_NEW = b"def new():\n    return 3\n"


def _digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _git(root: Path, *args: str) -> str:
    command = ["git", "-C", str(root), "-c", "user.name=fixture"]
    command += [
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
    ]
    done = subprocess.run([*command, *args], check=True, capture_output=True, text=True)
    return done.stdout


def _commit(root: Path, files: dict[str, bytes], message: str) -> None:
    for path, content in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(content)
        _git(root, "add", "--", path)
    _git(root, "commit", "-q", "-m", message)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _commit(root, {"pkg/util.py": _UTIL, "pkg/app.py": _APP}, "main")
    _git(root, "tag", "v1")
    _git(root, "checkout", "-q", "-b", "feature")
    _commit(root, {"pkg/app.py": _APP_FEATURE, "pkg/new.py": _NEW}, "feature")
    return root


class _Graph:
    """Engine stand-in answering with a typed result, one outcome per blob."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[tuple[str, bytes]], IndexRepositoryScope]] = []
        self.graphs: set[str | None] = set()

    async def index_repository(
        self,
        files: list[tuple[str, bytes]],
        *,
        scope: IndexRepositoryScope,
        graph: str | None,
    ) -> IndexResult:
        self.calls.append((files, scope))
        self.graphs.add(graph)
        outcomes = [
            {
                "file_path": path,
                "status": "success",
                "content_digest": _digest(content),
                "parser_capability_digest": f"sha256:{'c' * 64}",
                "diagnostics": [],
            }
            for path, content in files
        ]
        counters = dict.fromkeys(
            [
                "symbols_extracted",
                "calls_resolved",
                "calls_unresolved",
                "calls_scope_resolved",
                "calls_type_resolved",
                "inherits_edges",
                "realizes_edges",
                "similar_edges",
                "imports_resolved",
                "imports_unresolved",
            ],
            0,
        )
        payload: dict[str, Any] = {"nodes": [], "edges": [], "file_outcomes": outcomes}
        return IndexResult.model_validate(
            {**payload, **counters, "files_parsed": len(files)}
        )

    def submitted(self) -> list[tuple[str, bytes]]:
        return [item for files, _ in self.calls for item in files]

    def memberships(self) -> set[tuple[str, str, str]]:
        return {
            (item.ref_name, item.path, item.blob_digest)
            for _, scope in self.calls
            for item in scope.file_versions
        }

    def tombstones(self) -> set[tuple[str, str, str | None]]:
        return {
            (item.ref_name, item.path, item.successor_path)
            for _, scope in self.calls
            for item in scope.tombstones
        }


class _CountingProvider(LocalGitRepositoryProvider):
    fetched: list[str]

    async def fetch_blob(self, revision: RepositoryRevision, blob_id: str) -> bytes:
        self.fetched = [*getattr(self, "fetched", []), blob_id]
        return await super().fetch_blob(revision, blob_id)


def _client(graph: _Graph) -> EpistemicGraphClient:
    return cast(EpistemicGraphClient, type("Client", (), {"graph": graph})())


async def _index(
    provider: LocalGitRepositoryProvider,
    engine: _Graph,
    **options: Any,
) -> RepositoryIndexReceipt:
    return await index_repository(provider, _client(engine), **options)


def _provider(root: Path) -> _CountingProvider:
    return _CountingProvider(root, repository_id="team/project")


def _expected_memberships() -> set[tuple[str, str, str]]:
    shared = {("pkg/util.py", _UTIL), ("pkg/app.py", _APP)}
    feature = {
        ("pkg/util.py", _UTIL),
        ("pkg/app.py", _APP_FEATURE),
        ("pkg/new.py", _NEW),
    }
    refs = {
        "refs/heads/main": shared,
        "refs/tags/v1": shared,
        "refs/heads/feature": feature,
    }
    return {
        (ref, path, _digest(content))
        for ref, files in refs.items()
        for path, content in files
    }


async def test_each_unique_blob_is_fetched_and_submitted_once(repository: Path) -> None:
    provider, graph = _provider(repository), _Graph()

    receipt = await _index(provider, graph)

    assert isinstance(provider, RepositorySnapshotProvider)
    submitted = graph.submitted()
    assert sorted(content for _, content in submitted) == sorted(
        [_UTIL, _APP, _APP_FEATURE, _NEW]
    )
    assert len(provider.fetched) == len(set(provider.fetched)) == 4
    assert receipt.blobs_fetched == 4
    assert receipt.blobs_reused == 0
    assert [path for path, _ in submitted] == sorted(path for path, _ in submitted)


async def test_every_ref_keeps_exactly_its_own_memberships(repository: Path) -> None:
    graph = _Graph()

    receipt = await _index(_provider(repository), graph, graph="repositories")

    assert graph.graphs == {"repositories"}
    assert graph.memberships() == _expected_memberships()
    assert isinstance(receipt.manifest, RepositoryIndexManifest)
    assert all(isinstance(ref, RepositoryRefManifest) for ref in receipt.manifest.refs)
    assert receipt.batches
    assert all(isinstance(batch, RepositoryBatchReceipt) for batch in receipt.batches)
    refs = {ref.ref_name: ref for ref in receipt.manifest.refs}
    assert sorted(refs) == ["refs/heads/feature", "refs/heads/main", "refs/tags/v1"]
    feature = refs["refs/heads/feature"].snapshot
    assert [item.path for item in feature.files] == [
        "pkg/app.py",
        "pkg/new.py",
        "pkg/util.py",
    ]
    assert graph.tombstones() == set()
    declared = {item.ref_name for item in graph.calls[0][1].refs}
    assert declared == set(refs)


async def test_bounded_batches_bind_each_blob_in_its_own_call(repository: Path) -> None:
    graph = _Graph()
    limits = RepositoryBatchLimits(max_files=1, max_file_versions=2)

    await _index(_provider(repository), graph, limits=limits)

    assert graph.memberships() == _expected_memberships()
    for files, scope in graph.calls:
        assert len(files) <= 1
        assert len(scope.file_versions) + len(scope.tombstones) <= 2
        bound = {(item.path, item.blob_digest) for item in scope.file_versions}
        assert {(path, _digest(content)) for path, content in files} <= bound


async def test_rerun_reuses_blobs_and_tombstones_what_left(repository: Path) -> None:
    first = await _index(_provider(repository), _Graph())
    _git(repository, "mv", "pkg/util.py", "pkg/shared.py")
    _git(repository, "rm", "-q", "pkg/new.py")
    _git(repository, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "move")
    _git(repository, "tag", "-d", "v1")
    provider, graph = _provider(repository), _Graph()

    second = await _index(provider, graph, prior=first.manifest)

    assert getattr(provider, "fetched", []) == []
    assert graph.submitted() == []
    assert second.blobs_reused == 3
    v1_removed = {
        ("refs/tags/v1", "pkg/app.py", None),
        ("refs/tags/v1", "pkg/util.py", None),
    }
    assert graph.tombstones() == {
        ("refs/heads/feature", "pkg/new.py", None),
        ("refs/heads/feature", "pkg/util.py", "pkg/shared.py"),
        *v1_removed,
    }
    deleted = [ref for ref in second.manifest.refs if ref.deleted]
    assert [ref.ref_name for ref in deleted] == ["refs/tags/v1"]


async def test_manifest_fingerprint_is_deterministic(repository: Path) -> None:
    first = await _index(_provider(repository), _Graph())
    second = await _index(_provider(repository), _Graph())

    assert first.manifest.fingerprint == second.manifest.fingerprint
    assert first.manifest.fingerprint.startswith("sha256:")


async def test_blob_content_must_match_its_object_id(repository: Path) -> None:
    class _Tampering(LocalGitRepositoryProvider):
        async def fetch_blob(self, revision: RepositoryRevision, blob_id: str) -> bytes:
            return b"tampered" + await super().fetch_blob(revision, blob_id)

    provider = _Tampering(repository, repository_id="team/project")
    with pytest.raises(RepositoryTransportError, match="does not match"):
        await _index(provider, _Graph())
