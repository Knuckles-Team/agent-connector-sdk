"""Repository transport models reject mutable or ambiguous source evidence."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from agent_connector_sdk.repository import (
    RepositoryManifestFile,
    RepositorySnapshotManifest,
)
from agent_connector_sdk.repository.models import (
    RepositoryAuthentication,
    RepositoryBatchLimits,
    RepositoryFile,
    RepositoryPage,
    RepositoryRevision,
    RepositoryTombstone,
)


def _digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _file(path: str, content: bytes) -> RepositoryFile:
    return RepositoryFile(path=path, blob_digest=_digest(content), content=content)


def _revision() -> RepositoryRevision:
    return RepositoryRevision(
        provider="git-forge",
        repository_id="team/project",
        revision_id="a" * 40,
        tree_id="b" * 40,
    )


def test_repository_transport_models_preserve_revision_auth_and_tombstone() -> None:
    auth = RepositoryAuthentication(
        provider="git-forge",
        principal="service:connector",
        mechanism="bearer",
        credential_reference_digest=f"sha256:{'c' * 64}",
    )
    deleted = RepositoryTombstone(
        path="old.py",
        prior_blob_digest=f"sha256:{'d' * 64}",
        successor_path="new.py",
    )
    page = RepositoryPage(
        revision=_revision(),
        files=(_file("src/main.py", b"print('ok')\n"),),
        tombstones=(deleted,),
    )

    assert auth.credential_reference_digest == f"sha256:{'c' * 64}"
    assert page.revision.tree_id == "b" * 40
    assert page.tombstones == (deleted,)


@pytest.mark.parametrize("path", ["", "/root.py", "a/../b.py", "a//b.py"])
def test_repository_file_rejects_non_logical_paths(path: str) -> None:
    with pytest.raises(ValidationError, match=r"normalized|relative"):
        _file(path, b"source")


def test_repository_file_rejects_content_digest_mismatch() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        RepositoryFile(
            path="main.py",
            blob_digest=f"sha256:{'0' * 64}",
            content=b"source",
        )


def test_repository_revision_rejects_mutable_ref_names() -> None:
    with pytest.raises(ValidationError, match="immutable"):
        RepositoryRevision(
            provider="git-forge",
            repository_id="team/project",
            revision_id="main",
            tree_id="b" * 40,
        )


def test_repository_page_rejects_duplicate_active_and_tombstone_path() -> None:
    with pytest.raises(ValidationError, match="unique"):
        RepositoryPage(
            revision=_revision(),
            files=(_file("main.py", b"source"),),
            tombstones=(
                RepositoryTombstone(
                    path="main.py", prior_blob_digest=f"sha256:{'f' * 64}"
                ),
            ),
        )


def test_repository_batch_limits_reject_file_limit_larger_than_batch() -> None:
    with pytest.raises(ValidationError, match="must not exceed"):
        RepositoryBatchLimits(max_bytes=2, max_file_bytes=3)


def test_snapshot_manifest_fingerprint_is_order_independent() -> None:
    first = RepositoryManifestFile(
        path="a.py", blob_digest=f"sha256:{'a' * 64}", byte_length=1
    )
    second = RepositoryManifestFile(
        path="b.py", blob_digest=f"sha256:{'b' * 64}", byte_length=2
    )

    left = RepositorySnapshotManifest(revision=_revision(), files=(first, second))
    right = RepositorySnapshotManifest(revision=_revision(), files=(second, first))

    assert left.files == (first, second)
    assert right.files == left.files
    assert right.fingerprint == left.fingerprint
