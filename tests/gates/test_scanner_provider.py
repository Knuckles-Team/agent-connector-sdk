"""The SDK delegates scanner provenance to the audited shared provider."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).parents[2] / "scripts/install_scanners.sh"
RECORDER = r"""
import json
import os
import sys
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
phase = name
if name == "git":
    phase = args[2]
    if any(key.startswith("GIT_") for key in os.environ):
        raise SystemExit("repository selectors leaked to provider")
elif name == "python3":
    phase = "toolchain" if args[0] == "-" else "provider"
with open(os.environ["RECORDER_LOG"], "a") as stream:
    stream.write(json.dumps({"phase": phase, "args": args}) + "\n")
if phase == os.environ.get("FAIL_PHASE"):
    raise SystemExit(23)
if phase == "rev-parse":
    print(os.environ["PROVIDER_REVISION"])
elif phase == "toolchain":
    assert "from pipelines_hooks.core.jscpd_build import RUST_TOOLCHAIN" in sys.stdin.read()
    print("9.8.7-provider")
elif phase == "provider":
    assert args[1] == "--root"
    print(str(Path(args[2]) / "verified/bin"))
"""


@pytest.fixture
def provider_commands(tmp_path: Path):
    script = INSTALLER.read_text()
    match = re.search(r'^provider_commit="([0-9a-f]{40})"$', script, re.MULTILINE)
    assert match, "provider must be pinned to an immutable commit"
    commands = tmp_path / "commands"
    commands.mkdir()
    for name in ("git", "python3", "rustup"):
        command = commands / name
        command.write_text(f"#!{sys.executable}\n" + RECORDER)
        command.chmod(0o755)
    root = tmp_path / "scanner root"
    root.mkdir()
    log = tmp_path / "calls.jsonl"
    env = {
        **os.environ,
        "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
        "RECORDER_LOG": str(log),
        "PROVIDER_REVISION": match[1],
        "GIT_DIR": str(tmp_path / "foreign.git"),
        "GIT_WORK_TREE": str(tmp_path / "foreign-tree"),
    }
    block = script[script.index("# The shared provider") : script.index("ln -sf")]
    return root, log, env, block


def _run(fixture, **overrides: str):
    root, log, env, block = fixture
    result = subprocess.run(
        [
            "bash",
            "-c",
            "set -euo pipefail\nroot=" + shlex.quote(str(root)) + "\n" + block,
        ],
        env={**env, **overrides},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result, calls


def test_provider_owns_identity_toolchain_and_cached_verification(provider_commands):
    root, _, env, _ = provider_commands
    for _ in range(2):
        result, calls = _run(provider_commands)
        assert result.returncode == 0, result.stderr
    assert [call["phase"] for call in calls] == [
        "init",
        "fetch",
        "checkout",
        "rev-parse",
        "toolchain",
        "rustup",
        "provider",
    ] * 2
    assert calls[1]["args"][-1] == env["PROVIDER_REVISION"]
    assert calls[2]["args"][-2:] == ["--detach", "FETCH_HEAD"]
    assert calls[5]["args"] == [
        "toolchain",
        "install",
        "9.8.7-provider",
        "--profile",
        "minimal",
    ]
    assert calls[6]["args"][1:] == ["--root", str(root / "jscpd")]
    assert not list(root.glob("pipelines-provider.*"))
    assert not list(root.rglob("*.provenance.json"))
    script = INSTALLER.read_text()
    assert 'ln -sf "$jscpd_bin_dir/jscpd" "$bin/jscpd"' in script
    assert "npm install" not in script
    assert "JSCPD_VERSION=" not in script


@pytest.mark.parametrize(
    "phase",
    ["init", "fetch", "checkout", "rev-parse", "toolchain", "rustup", "provider"],
)
def test_provider_failure_stops_installation(provider_commands, phase: str):
    root, _, _, _ = provider_commands
    result, calls = _run(provider_commands, FAIL_PHASE=phase)
    assert result.returncode == 23
    assert calls[-1]["phase"] == phase
    assert not list(root.glob("pipelines-provider.*"))


def test_provider_revision_mismatch_refuses_execution(provider_commands):
    result, calls = _run(provider_commands, PROVIDER_REVISION="0" * 40)
    assert result.returncode == 1
    assert "Scanner provider revision mismatch" in result.stderr
    assert calls[-1]["phase"] == "rev-parse"
