"""Structural contracts between the release workflow, the hook config and scripts.

These tests pin no revision or version by value: each pin lives in exactly one
source file, and the tests prove the files agree with each other and stay
immutable (full commit digests), so bumping a pin never needs a test edit.
Knuckles-Team/pipelines is the one sanctioned exception to that immutability
rule: every repository consumes it at its `main` branch, never a commit SHA or
tag (operator ruling, plans/refactor/DECISIONS.md; enforced fleet-wide by
pipelines_hooks/supply_chain/{precommit,workflows}.py), so pins to it are
checked against `main` instead of a commit digest.
"""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
PRE_COMMIT = ROOT / ".config" / "pre-commit.yaml"
BOOTSTRAP = ROOT / "scripts" / "bootstrap.sh"
CONTRACT = ROOT / "scripts" / "bootstrap_epistemic_graph_contract.sh"
SCANNERS = ROOT / "scripts" / "install_scanners.sh"
PIPELINES = "https://github.com/Knuckles-Team/pipelines"
PIPELINES_USES_RE = re.compile(r"^Knuckles-Team/pipelines(?:/|$)", re.IGNORECASE)
COMMIT = re.compile(r"[0-9a-f]{40}")
UV_ACTION = "astral-sh/setup-uv@"


def _yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _pipelines_rev() -> str:
    config = _yaml(PRE_COMMIT)
    return next(r["rev"] for r in config["repos"] if r.get("repo") == PIPELINES)


def _runs(job: dict[str, Any]) -> list[str]:
    return [str(step.get("run", "")) for step in job.get("steps", [])]


def test_shared_hooks_pin_pipelines_to_the_sanctioned_main_exception() -> None:
    assert _pipelines_rev() == "main"


def test_pages_uses_the_same_pipelines_revision_as_the_hooks() -> None:
    pages = _yaml(PAGES)["jobs"]["pages"]
    workflow, _, rev = pages["uses"].partition("@")

    assert workflow == "Knuckles-Team/pipelines/.github/workflows/pages_pipeline.yml"
    assert rev == _pipelines_rev()
    assert "steps" not in pages
    assert pages["with"] == {"content_source": "docs", "shared_theme_enabled": True}
    assert pages["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }


def test_gates_job_runs_whole_hook_stages_not_hand_listed_hooks() -> None:
    runs = _runs(_yaml(RELEASE)["jobs"]["gates"])
    stages = {
        match.group(1)
        for command in runs
        if "--all-files" in command
        for match in [re.search(r"--hook-stage (\S+)", command)]
        if match and "pre-commit run --config" in command
    }

    assert "scripts/bootstrap.sh" in runs
    assert {"pre-commit", "pre-push"} <= stages
    assert not any("for hook in" in command for command in runs)


def test_every_pre_commit_invocation_uses_the_relocated_config() -> None:
    for path in (RELEASE, BOOTSTRAP):
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"pre-commit (run|install)\b", line):
                assert "--config .config/pre-commit.yaml" in line, (path, line)


def test_every_release_job_using_uvx_installs_uv_first() -> None:
    for name, job in _yaml(RELEASE)["jobs"].items():
        steps = job.get("steps", [])
        uvx = [i for i, s in enumerate(steps) if "uvx " in str(s.get("run", ""))]
        if not uvx:
            continue
        setup = [
            i
            for i, s in enumerate(steps)
            if str(s.get("uses", "")).startswith(UV_ACTION)
        ]
        assert setup, f"{name} uses uvx without setup-uv"
        assert min(setup) < min(uvx)


def test_workflow_actions_are_pinned_to_immutable_commits() -> None:
    for path in (RELEASE, PAGES):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"uses:\s*([^\s#]+)", line)
            if match and not match.group(1).startswith("./"):
                action, _, ref = match.group(1).rpartition("@")
                if PIPELINES_USES_RE.match(action):
                    assert ref == "main", (path.name, line.strip())
                else:
                    assert COMMIT.fullmatch(ref), (path.name, line.strip())


def test_scanner_toolchain_comes_from_the_single_install_script() -> None:
    scanner = _yaml(RELEASE)["jobs"]["scanner-quality"]
    runs = "\n".join(_runs(scanner))
    caches = [
        step
        for step in scanner["steps"]
        if str(step.get("uses", "")).startswith("actions/cache@")
    ]
    script = SCANNERS.read_text(encoding="utf-8")
    cccc_rev = re.search(r"^CCCC_REV=(\S+)$", script, re.MULTILINE)

    assert "bash scripts/install_scanners.sh" in runs
    assert "cargo install" not in runs
    assert "npm install" not in runs
    assert caches
    assert "hashFiles('scripts/install_scanners.sh')" in caches[0]["with"]["key"]
    assert "bash scripts/install_scanners.sh" in BOOTSTRAP.read_text(encoding="utf-8")
    # cccc 1.6 is not on crates.io; it must come from an immutable upstream commit.
    assert cccc_rev
    assert COMMIT.fullmatch(cccc_rev.group(1))
    assert '--git "$CCCC_GIT" --rev "$CCCC_REV"' in script


def test_generated_contract_source_is_fetched_at_an_immutable_commit() -> None:
    gates = _yaml(RELEASE)["jobs"]["gates"]
    contract = CONTRACT.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    revision = re.search(r"^revision=(\S+)$", contract, re.MULTILINE)

    assert gates["env"]["PYTHONPATH"] == ".ci/epistemic-graph"
    assert revision
    assert COMMIT.fullmatch(revision.group(1))
    assert 'git -C "$target" checkout --detach "$revision"' in contract
    assert "bash scripts/bootstrap_epistemic_graph_contract.sh" in bootstrap
    assert "uv sync --frozen" in bootstrap
    assert "--no-install-package epistemic-graph" in bootstrap
    assert any("epistemic_graph.generated.source_ingestion" in r for r in _runs(gates))


def test_no_gate_depends_on_an_external_audit_service() -> None:
    hook_ids = {
        hook["id"] for repo in _yaml(PRE_COMMIT)["repos"] for hook in repo["hooks"]
    }

    assert "dependency-audit" not in hook_ids
    assert "osv" not in RELEASE.read_text(encoding="utf-8").lower()


def test_publish_requires_the_dependency_floor_on_the_public_index() -> None:
    commands = _runs(_yaml(RELEASE)["jobs"]["publish-pypi"])

    assert commands.index("uv lock --check") < commands.index(
        "uv publish --trusted-publishing always dist/*.whl"
    )
