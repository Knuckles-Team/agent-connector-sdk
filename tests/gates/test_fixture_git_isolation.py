"""Git fixtures must not mutate the repository invoking a linked-worktree hook."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        },
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_fixture_modules_preserve_invoking_worktree(tmp_path: Path) -> None:
    caller = tmp_path / "caller"
    caller.mkdir()
    _git(caller, "init", "-q")
    _git(
        caller,
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--allow-empty",
        "-qm",
        "caller",
    )
    linked = tmp_path / "linked"
    _git(caller, "worktree", "add", "-qb", "fixture-caller", str(linked))
    sentinel = linked / "keep.txt"
    sentinel.write_text("caller staged content\n")
    _git(linked, "add", "--", "keep.txt")
    git_dir = Path(_git(linked, "rev-parse", "--absolute-git-dir"))
    config = caller / ".git" / "config"
    index = git_dir / "index"
    before = (config.read_bytes(), index.read_bytes(), sentinel.read_bytes())
    env = {
        **os.environ,
        "GIT_DIR": str(git_dir),
        "GIT_COMMON_DIR": str(caller / ".git"),
        "GIT_WORK_TREE": str(linked),
        "GIT_INDEX_FILE": str(index),
        "GIT_PREFIX": "caller/",
    }
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "tests/gates/test_gates_fire.py",
            "tests/test_repository_refwalk_fastpath.py",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    after = (config.read_bytes(), index.read_bytes(), sentinel.read_bytes())
    assert after == before, "fixture Git commands changed the invoking repository"
    assert result.returncode == 0, result.stdout + result.stderr
