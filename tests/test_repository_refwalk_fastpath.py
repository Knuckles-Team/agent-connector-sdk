"""Focused checks for Git tree batching across refs and nested trees.

Proves SDK-REPOSITORY-TRANSPORT-R003: the walk phase visits each distinct Git
tree once and reads objects in batches, and its output matches a plain
recursive ``git ls-tree`` listing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent_connector_sdk.repository.local_git import LocalGitRepositoryProvider
from agent_connector_sdk.repository.walk import RefTree, walk_refs

pytestmark = pytest.mark.usefixtures("isolated_git_environment")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")


@pytest.mark.spec("SDK-REPOSITORY-TRANSPORT-R003")
async def test_distinct_commits_with_one_tree_walk_once(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _init_repo(root)
    (root / "nested").mkdir()
    (root / "nested" / "file.txt").write_text("shared\n")
    (root / "run.sh").write_text("#!/bin/sh\nexit 0\n")
    (root / "run.sh").chmod(0o755)
    (root / "link").symlink_to("nested/file.txt")
    _git(root, "add", "--", "nested/file.txt", "run.sh", "link")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "first")
    _git(root, "tag", "v1")
    _git(
        root,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--allow-empty",
        "-q",
        "-m",
        "second",
    )

    provider = LocalGitRepositoryProvider(root, repository_id="fixture")
    trees, pages = await walk_refs(provider, page_size=2)

    assert all(isinstance(tree, RefTree) for tree in trees)
    assert [tree.ref.name for tree in trees] == ["refs/heads/main", "refs/tags/v1"]
    assert len({tree.ref.revision.revision_id for tree in trees}) == 2
    assert len({tree.ref.revision.tree_id for tree in trees}) == 1
    assert pages == 2
    assert trees[0].entries == trees[1].entries
    assert [entry.path for entry in trees[0].entries] == [
        "link",
        "nested/file.txt",
        "run.sh",
    ]


@pytest.mark.spec("SDK-REPOSITORY-TRANSPORT-R003")
async def test_batch_matches_git_recursive_listing(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _init_repo(root)
    for depth in ("a", "b/c", "b/d"):
        directory = root / depth
        directory.mkdir(parents=True)
        (directory / "same.txt").write_text("shared\n")
    _git(root, "add", "--", "a", "b")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "first")
    _git(root, "checkout", "-q", "-b", "other")
    (root / "b" / "c" / "same.txt").write_text("changed\n")
    _git(root, "add", "--", "b/c/same.txt")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "second")

    provider = LocalGitRepositoryProvider(root, repository_id="fixture")
    refs = await provider.list_refs()
    expected = {}
    for ref in refs:
        listing = _git(root, "ls-tree", "-r", "--full-tree", ref.revision.tree_id)
        expected[ref.name] = {
            path: meta.split()[2]
            for record in listing.splitlines()
            for meta, path in [record.split("\t", 1)]
            if meta.split()[1] == "blob"
        }

    trees, _ = await walk_refs(provider, page_size=1)
    assert {
        tree.ref.name: {entry.path: entry.blob_id for entry in tree.entries}
        for tree in trees
    } == expected


@pytest.mark.parametrize("linked", [False, True])
async def test_provider_ignores_inherited_repository_selectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, linked: bool
) -> None:
    target = tmp_path / "target"
    foreign = tmp_path / "foreign"
    for root in (target, foreign):
        _init_repo(root)
        (root / "content.txt").write_text(root.name)
        _git(root, "add", "--", "content.txt")
        _git(root, "-c", "commit.gpgsign=false", "commit", "-qm", root.name)
    if linked:
        worktree = tmp_path / "linked"
        _git(target, "worktree", "add", "-qb", "linked", str(worktree))
        target = worktree
    provider = LocalGitRepositoryProvider(target, repository_id="requested")
    refs = await provider.list_refs()
    revision = refs[0].revision
    expected = await provider.list_tree(revision, cursor=None, page_size=10)
    selectors = {
        "GIT_DIR": str(foreign / ".git"),
        "GIT_COMMON_DIR": str(foreign / ".git"),
        "GIT_WORK_TREE": str(foreign),
        "GIT_INDEX_FILE": str(foreign / ".git" / "index"),
        "GIT_OBJECT_DIRECTORY": str(foreign / ".git" / "objects"),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(foreign / ".git" / "objects"),
        "GIT_NAMESPACE": "foreign",
        "GIT_PREFIX": "foreign/",
    }
    for name, value in selectors.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "fixture.retained")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "retained")

    direct = LocalGitRepositoryProvider(target, repository_id="requested")
    assert await direct.list_refs() == refs
    assert await direct.list_tree(revision, cursor=None, page_size=10) == expected
    assert await direct.fetch_blob(revision, expected.entries[0].blob_id) == b"target"
    batched = LocalGitRepositoryProvider(target, repository_id="requested")
    await batched.prime_trees((revision.tree_id,))
    assert await batched.list_tree(revision, cursor=None, page_size=10) == expected
    assert await batched._git("config", "--get", "fixture.retained") == b"retained\n"
    assert {name: os.environ[name] for name in selectors} == selectors
