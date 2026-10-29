"""Structural contracts between the release workflow, the hook config and scripts.

These tests pin no revision or version by value: each pin lives in exactly one
source file, and the tests prove the files agree with each other and stay
immutable (full commit digests), so bumping a pin never needs a test edit.
Knuckles-Team/pipelines is the one sanctioned exception to that immutability
rule: every repository consumes it at its `main` branch, never a commit SHA or
tag (fleet standard, enforced by
pipelines_hooks/supply_chain/{precommit,workflows}.py), so pins to it are
checked against `main` instead of a commit digest.
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
GATES = ROOT / ".github" / "workflows" / "ci.yml"
BUILD = ROOT / ".github" / "workflows" / "build.yml"
SETUP_UV_ACTION = ROOT / ".github" / "actions" / "setup-uv" / "action.yml"
CI_SETUP = ROOT / "scripts" / "ci_setup.sh"
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
    assert pages["with"] == {
        "content_source": "docs",
        "shared_theme_enabled": True,
        "spec_dashboard_enabled": True,
    }
    assert pages["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }


def test_gates_job_is_the_shared_diff_scoped_workflow() -> None:
    workflow = _yaml(GATES)
    gates = workflow["jobs"]["gates"]

    assert (
        gates["uses"]
        == "Knuckles-Team/pipelines/.github/workflows/gates_pipeline.yml@main"
    )
    assert "steps" not in gates
    assert gates["with"]["setup-command"] == "bash scripts/ci_setup.sh"
    assert gates["if"] == "github.event_name == 'pull_request'"
    assert gates["with"]["timeout-minutes"] == 45


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005")
def test_gates_uv_cache_is_workspace_local_and_job_scoped() -> None:
    gates = _yaml(GATES)["jobs"]["gates"]
    assert gates["with"]["uv-cache-local-path"] == (
        ".ci/uv-cache-${{ github.run_id }}-${{ github.run_attempt }}"
    )
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".ci/uv-cache-123-1"],
        cwd=ROOT,
        check=False,
    )
    assert ignored.returncode == 0


def test_ci_triggers_follow_the_fleet_standard_and_cancel_superseded_runs() -> None:
    workflow = _yaml(GATES)
    triggers = workflow[True]

    # Pull requests always run the one `gates / gates` check; the job detects a
    # docs-only diff itself, so no same-named skip companion exists.
    assert triggers["pull_request"] == {"branches": ["main"]}
    assert triggers["push"] == {"branches": ["main"]}
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert not (GATES.parent / "gates-skip.yml").exists()
    patterns = workflow["jobs"]["gates"]["with"]["docs-only-paths"].split()
    assert patterns == ["specs/*", "docs/*", "*.md", "plans/*", "LICENSE"]
    assert workflow["concurrency"]["cancel-in-progress"] is True


def test_ci_required_aggregates_every_blocking_job() -> None:
    jobs = _yaml(GATES)["jobs"]
    required = jobs["ci-required"]

    assert required["name"] == "CI required"
    assert required["if"] == "always()"
    assert set(required["needs"]) == {"gates", "main-gates", "full", "build"}
    assert jobs["full"]["if"] == "github.event_name != 'pull_request'"
    assert jobs["full"]["with"]["backward-python"] == "3.12"


def test_release_publishes_only_for_a_tag_or_dispatch() -> None:
    workflow = _yaml(RELEASE)
    triggers = workflow[True]

    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"tags": ["v*"]}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert set(workflow["jobs"]) == {"build", "publish-pypi", "github-release"}
    release = workflow["jobs"]["github-release"]
    assert release["needs"] == ["publish-pypi"]
    assert release["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert release["permissions"] == {"contents": "write"}
    notes = release["steps"][0]["run"]
    assert "https://pypi.org/project/scion-sdk/$version/" in notes
    assert "--latest" in notes
    assert workflow["jobs"]["build"]["uses"] == "./.github/workflows/build.yml"
    assert "[skip ci]" not in RELEASE.read_text(encoding="utf-8")


@pytest.mark.spec("SCION-QUALITY-RELEASE-R003")
def test_release_builds_and_downloads_the_old_name_forwarder() -> None:
    build = _yaml(BUILD)["jobs"]["build-compat"]
    assert any(
        "check_compatibility_distribution.py" in command for command in _runs(build)
    )
    upload = next(
        step
        for step in build["steps"]
        if step.get("name") == "Upload the compatibility publish candidate"
    )
    assert upload["with"]["name"] == "agent-connector-sdk-compat"
    assert "dist-compat/*.whl" in upload["with"]["path"]
    assert "dist-compat/*.tar.gz" in upload["with"]["path"]

    publish = _yaml(RELEASE)["jobs"]["publish-pypi"]
    downloads = [
        step.get("with", {}).get("name")
        for step in publish["steps"]
        if "actions/download-artifact@" in str(step.get("uses", ""))
    ]
    assert downloads == ["scion-sdk-wheel", "agent-connector-sdk-compat"]
    publish_commands = _runs(publish)
    scion_publish = next(
        command for command in publish_commands if "dist/scion_sdk-" in command
    )
    alias_publish = next(
        command
        for command in publish_commands
        if "dist/agent_connector_sdk-" in command
    )
    assert "dist/scion_sdk-*.whl" in scion_publish
    assert "dist/scion_sdk-*.tar.gz" in scion_publish
    assert "dist/agent_connector_sdk-*.whl" in alias_publish
    assert "dist/agent_connector_sdk-*.tar.gz" in alias_publish
    assert publish_commands.index(scion_publish) < publish_commands.index(alias_publish)


def test_ci_setup_bootstraps_the_contract_and_identity_catalog() -> None:
    script = CI_SETUP.read_text(encoding="utf-8")

    assert "scripts/bootstrap.sh" in script
    assert "PYTHONPATH" not in script
    assert ".ci/epistemic-graph" not in script
    assert "PROHIBITED_IDENTITY_CATALOG" in script


@pytest.mark.spec("SCION-QUALITY-RELEASE-R005")
def test_bootstrap_installs_eg_from_its_pypi_wheel_only() -> None:
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    assert "uv sync --frozen" in bootstrap
    assert "bash scripts/bootstrap_epistemic_graph_contract.sh" in bootstrap
    for text in (bootstrap, contract, PRE_COMMIT.read_text(encoding="utf-8")):
        assert "--no-install-package epistemic-graph" not in text
        assert ".ci/epistemic-graph" not in text
        assert "PYTHONPATH=" not in text
    assert "epistemic_graph.generated.source_ingestion" in contract
    assert "https://pypi.org/" in contract

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    uv = pyproject["tool"]["uv"]
    assert "epistemic-graph" in uv["no-build-package"]
    assert "epistemic-graph" not in uv.get("sources", {})
    assert "dependency-metadata" not in uv

    script = CI_SETUP.read_text(encoding="utf-8")
    assert "uv run --frozen python" not in script


@pytest.mark.spec("SCION-QUALITY-RELEASE-R003")
def test_bootstrap_python_floor_uses_root_project_metadata(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "test-sdk"\n'
        'requires-python = ">=3.12,<3.15"\n'
        "[tool.uv]\n"
        'no-build-package = ["epistemic-graph"]\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "project_python_floor.py"),
            str(pyproject),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "3.12\n"
    assert (
        "python_version=$(tr -d '[:space:]' < .python-version)"
        in BOOTSTRAP.read_text(encoding="utf-8")
    )


def test_every_pre_commit_invocation_uses_the_relocated_config() -> None:
    for path in (GATES, RELEASE, BOOTSTRAP):
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"pre-commit (run|install)\b", line):
                assert "--config .config/pre-commit.yaml" in line, (path, line)


@pytest.mark.spec("SCION-QUALITY-RELEASE-R003")
def test_build_job_pins_the_managed_python_not_the_system_one() -> None:
    """Both build jobs share one pinned setup action after checkout."""
    workflow = _yaml(BUILD)
    pinned_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert pinned_version == "3.14"

    action = _yaml(SETUP_UV_ACTION)
    assert action["runs"]["using"] == "composite"
    uv_setup_steps = [
        step
        for step in action["runs"]["steps"]
        if str(step.get("uses", "")).startswith(UV_ACTION)
    ]
    assert len(uv_setup_steps) == 1
    assert uv_setup_steps[0]["with"]["python-version"] == pinned_version

    for job_name in ("build", "build-compat"):
        job = workflow["jobs"][job_name]
        checkout_steps = [
            step
            for step in job["steps"]
            if str(step.get("uses", "")).startswith("actions/checkout@")
        ]
        assert len(checkout_steps) == 1, (
            f"{job_name} must check out before local actions"
        )
        assert job["steps"].index(checkout_steps[0]) < next(
            index
            for index, step in enumerate(job["steps"])
            if step.get("uses") == "./.github/actions/setup-uv"
        )
        setup_steps = [
            step
            for step in job["steps"]
            if step.get("uses") == "./.github/actions/setup-uv"
        ]
        assert len(setup_steps) == 1, f"{job_name} must use the shared toolchain action"


@pytest.mark.spec("SCION-QUALITY-RELEASE-R001")
def test_build_job_verifies_installed_wheel_against_graph_client() -> None:
    """The release job must check the built wheel in an isolated installed
    consumer against the published graph-client wheel, not rely on the
    source-overlay test suite's own import of the repository checkout."""
    build = _yaml(BUILD)["jobs"]["build"]
    runs = _runs(build)
    assert any("check_wheel_consumer_compatibility.py" in command for command in runs)
    # The compatibility step must run after the wheel exists and before the
    # artifact is published, so a failing check blocks the release.
    names = [step.get("name", "") for step in build["steps"]]
    compat_index = next(i for i, name in enumerate(names) if "graph-client" in name)
    build_index = next(i for i, name in enumerate(names) if "Build the wheel" in name)
    upload_index = next(
        i for i, name in enumerate(names) if "Upload the publish candidate" in name
    )
    assert build_index < compat_index < upload_index


def test_every_release_job_using_uvx_installs_uv_first() -> None:
    for name, job in {
        **_yaml(RELEASE)["jobs"],
        **_yaml(GATES)["jobs"],
        **_yaml(BUILD)["jobs"],
    }.items():
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
    for path in (RELEASE, GATES, BUILD, PAGES):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"uses:\s*([^\s#]+)", line)
            if match and not match.group(1).startswith("./"):
                action, _, ref = match.group(1).rpartition("@")
                if PIPELINES_USES_RE.match(action):
                    assert ref == "main", (path.name, line.strip())
                else:
                    assert COMMIT.fullmatch(ref), (path.name, line.strip())


def test_scanner_toolchain_comes_from_the_single_install_script() -> None:
    scanner = _yaml(GATES)["jobs"]["scanner-quality"]
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


def test_no_gate_depends_on_an_external_audit_service() -> None:
    hook_ids = {
        hook["id"] for repo in _yaml(PRE_COMMIT)["repos"] for hook in repo["hooks"]
    }

    assert "dependency-audit" not in hook_ids
    assert "osv" not in GATES.read_text(encoding="utf-8").lower()


def test_publish_requires_the_dependency_floor_on_the_public_index() -> None:
    commands = _runs(_yaml(RELEASE)["jobs"]["publish-pypi"])

    publishes = [
        (index, command)
        for index, command in enumerate(commands)
        if "uv publish --check-url https://pypi.org/simple/" in command
    ]
    # Both package pairs publish only after the dependency lock check.
    assert len(publishes) == 2
    assert commands.index("uv lock --check") < min(index for index, _ in publishes)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R018")
def test_main_gate_runs_full_suite_types_and_docs() -> None:
    gates = _yaml(GATES)["jobs"]["main-gates"]
    assert gates["with"]["all-files"] is True
    # The suite runs once, in the `full` job; main-gates keeps hooks, wheel and docs.
    assert gates["with"]["test-scope"] == ""
    full = _yaml(GATES)["jobs"]["full"]["with"]
    assert full["setup-command"] == "bash scripts/ci_full_setup.sh"
    assert full["backward-module"] == "agent_connector_sdk"
    assert "mkdocs-build" in gates["with"]["extra-manual-hooks"]
    hooks = _yaml(PRE_COMMIT)["repos"]
    local_hooks = [
        hook for repo in hooks if repo.get("repo") == "local" for hook in repo["hooks"]
    ]
    mypy = next(hook for hook in local_hooks if hook["id"] == "mypy")
    assert "pre-push" in mypy["stages"]
    assert "mypy agent_connector_sdk" in mypy["entry"]
