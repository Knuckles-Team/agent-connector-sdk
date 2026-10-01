"""Ref/tree models and the ref-walk provider port reject malformed identity."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_connector_sdk.repository.local_git import LocalGitRepositoryProvider
from agent_connector_sdk.repository.models import RepositoryRevision
from agent_connector_sdk.repository.provider import RepositoryRefWalkProvider
from agent_connector_sdk.repository.refs import (
    RepositoryRef,
    RepositoryTreeEntry,
    RepositoryTreePage,
)


def _revision() -> RepositoryRevision:
    return RepositoryRevision(
        provider="git-forge",
        repository_id="team/project",
        revision_id="a" * 40,
        tree_id="b" * 40,
    )


def test_repository_tree_page_preserves_entries() -> None:
    page = RepositoryTreePage(
        revision=_revision(),
        entries=(RepositoryTreeEntry(path="src/main.py", blob_id="e" * 40),),
    )

    assert page.revision.tree_id == "b" * 40
    assert page.entries[0].path == "src/main.py"


def test_repository_tree_page_rejects_duplicate_paths() -> None:
    entry = RepositoryTreeEntry(path="main.py", blob_id="e" * 40)
    with pytest.raises(ValidationError, match="unique"):
        RepositoryTreePage(revision=_revision(), entries=(entry, entry))


def test_repository_tree_page_rejects_an_empty_continued_page() -> None:
    with pytest.raises(ValidationError, match="empty"):
        RepositoryTreePage(revision=_revision(), entries=(), next_cursor="1")


@pytest.mark.parametrize("blob_id", ["main", "E" * 40, "e" * 41])
def test_repository_tree_entry_rejects_mutable_blob_ids(blob_id: str) -> None:
    with pytest.raises(ValidationError, match="immutable"):
        RepositoryTreeEntry(path="main.py", blob_id=blob_id)


def test_repository_ref_rejects_unprintable_names() -> None:
    with pytest.raises(ValidationError, match="printable"):
        RepositoryRef(name="refs/heads/a\nb", revision=_revision())


def test_local_git_provider_satisfies_the_ref_walk_protocol(tmp_path: Path) -> None:
    provider = LocalGitRepositoryProvider(tmp_path, repository_id="fixture")

    assert isinstance(provider, RepositoryRefWalkProvider)
