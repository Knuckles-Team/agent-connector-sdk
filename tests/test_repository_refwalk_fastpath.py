"""Focused checks for Git tree batching across refs and nested trees."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_connector_sdk.repository.local_git import LocalGitRepositoryProvider
from agent_connector_sdk.repository.walk import walk_refs


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


async def test_distinct_commits_with_one_tree_walk_once(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
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


async def test_batch_matches_git_recursive_listing(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
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
