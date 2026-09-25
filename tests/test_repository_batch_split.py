"""Only an atomic EG size refusal may split a repository batch."""

from __future__ import annotations

import hashlib
from typing import Any, cast

import pytest
from epistemic_graph.client import EpistemicGraphClient
from epistemic_graph.generated.index_repository import IndexRepositoryScope, IndexResult

from agent_connector_sdk.repository.batching import RepositoryBatch
from agent_connector_sdk.repository.indexing import ScopeHeader
from agent_connector_sdk.repository.models import RepositoryFile, RepositoryTombstone
from agent_connector_sdk.repository.transport import _submit_with_split


def _file(path: str) -> RepositoryFile:
    content = path.encode("utf-8")
    return RepositoryFile(
        path=path,
        blob_digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
        content=content,
    )


def _batch() -> RepositoryBatch:
    files = [_file("a.py"), _file("b.py")]
    return RepositoryBatch(
        files=files,
        versions=[("refs/heads/main", item.path, item.blob_digest) for item in files],
        byte_count=sum(len(item.content) for item in files),
    )


_HEADER = ScopeHeader(
    graph="repositories",
    repository_id="local-git:fixture",
    refs=({"ref_name": "refs/heads/main", "revision_id": "a" * 40, "status": "live"},),
)


class _Graph:
    def __init__(self, refusal: str = "REPOSITORY_BATCH_TOO_LARGE: limit") -> None:
        self.refusal = refusal
        self.calls: list[tuple[tuple[str, ...], int, int]] = []
        self.committed: set[
            tuple[tuple[str, ...], tuple[tuple[str, str, str], ...]]
        ] = set()

    async def index_repository(
        self,
        files: list[tuple[str, bytes]],
        *,
        scope: IndexRepositoryScope,
        graph: str | None,
    ) -> IndexResult:
        assert graph == _HEADER.graph
        paths = tuple(path for path, _ in files)
        self.calls.append((paths, len(scope.file_versions), len(scope.tombstones)))
        if len(files) > 1 or (len(files) == 1 and self.refusal == "always"):
            message = (
                "REPOSITORY_BATCH_TOO_LARGE: one blob"
                if self.refusal == "always"
                else self.refusal
            )
            raise RuntimeError(message)
        if self.refusal == "PERMISSION_DENIED: no" and files:
            raise RuntimeError(self.refusal)
        versions = tuple(
            (item.ref_name, item.path, item.blob_digest) for item in scope.file_versions
        )
        self.committed.add((paths, versions))
        outcomes = [
            {
                "file_path": path,
                "status": "success",
                "content_digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
                "parser_capability_digest": f"sha256:{'c' * 64}",
                "diagnostics": [],
            }
            for path, content in files
        ]
        counters = dict.fromkeys(
            [
                "symbols_extracted",
                "files_parsed",
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
        return IndexResult.model_validate({**payload, **counters})


def _client(graph: _Graph) -> EpistemicGraphClient:
    return cast(EpistemicGraphClient, type("Client", (), {"graph": graph})())


async def test_size_refusal_splits_and_replay_is_idempotent() -> None:
    graph = _Graph()
    batch = _batch()

    first = await _submit_with_split(_client(graph), _HEADER, batch)
    second = await _submit_with_split(_client(graph), _HEADER, batch)

    assert [receipt.paths for receipt in first] == [("a.py",), ("b.py",)]
    assert [receipt.paths for receipt in second] == [receipt.paths for receipt in first]
    assert [receipt.file_versions for receipt in first] == [1, 1]
    assert len(graph.calls) == 6
    assert len(graph.committed) == 2


async def test_unrelated_refusal_is_not_retried() -> None:
    graph = _Graph("PERMISSION_DENIED: no")
    with pytest.raises(RuntimeError, match="PERMISSION_DENIED"):
        await _submit_with_split(_client(graph), _HEADER, _batch())
    assert len(graph.calls) == 1
    assert not graph.committed


async def test_unsplittable_blob_is_not_resent() -> None:
    graph = _Graph("always")
    batch = _batch()
    batch.files.pop()
    batch.versions.pop()
    with pytest.raises(RuntimeError, match="REPOSITORY_BATCH_TOO_LARGE"):
        await _submit_with_split(_client(graph), _HEADER, batch)
    assert len(graph.calls) == 1


async def test_split_keeps_primary_membership_and_all_metadata() -> None:
    graph = _Graph()
    batch = _batch()
    batch.versions.extend(
        ("refs/heads/main", f"alias{index}.py", batch.files[0].blob_digest)
        for index in range(3)
    )
    batch.tombstones.append(
        (
            "refs/heads/main",
            RepositoryTombstone(
                path="old.py", prior_blob_digest=batch.files[0].blob_digest
            ),
        )
    )

    receipts = await _submit_with_split(_client(graph), _HEADER, batch)

    assert sum(receipt.file_versions for receipt in receipts) == 5
    assert sum(receipt.tombstones for receipt in receipts) == 1
    assert sorted(path for receipt in receipts for path in receipt.paths) == [
        "a.py",
        "b.py",
    ]
    assert all(
        not paths or versions >= len(paths) for paths, versions, _ in graph.calls[1:]
    )
