"""Release workflow contracts that must remain executable on a clean runner."""

import re
from pathlib import Path

import pytest
import yaml

from scripts.check_eg_release_dependency import (
    require_error_catalog,
    require_lock_contract,
)

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
CCCC_REVISION = "d728759323be5d9977b7390a27133e8eaf481f26"
KISS_FORK_REVISION = "7f1c6785697d3fe9a41ceb8b8e5d0f615fb1f3d9"
PAGES_PIPELINE = "Knuckles-Team/pipelines/.github/workflows/pages_pipeline.yml@main"
UV_ACTION = "astral-sh/setup-uv@"


def test_release_installs_cccc_1_6_from_its_immutable_upstream_commit() -> None:
    workflow = RELEASE.read_text(encoding="utf-8")

    assert "cargo install --locked --version 1.6.0" not in workflow
    assert "--git https://github.com/moznion/cccc" in workflow
    assert f"--rev {CCCC_REVISION}" in workflow


def test_release_requires_the_pinned_kiss_fork_scanner_gate() -> None:
    document = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    scanner = document["jobs"]["scanner-quality"]
    commands = "\n".join(str(step.get("run", "")) for step in scanner["steps"])

    assert "continue-on-error" not in scanner
    assert "--git https://github.com/Knucklessg1/kiss" in commands
    assert f"--rev {KISS_FORK_REVISION}" in commands
    assert "--version 0.4.10" not in commands
    assert "scanner-quality" in document["jobs"]["build"]["needs"]


def test_pages_delegates_the_complete_site_pipeline_to_main() -> None:
    document = yaml.safe_load(PAGES.read_text(encoding="utf-8"))
    pages = document["jobs"]["pages"]

    assert pages["uses"] == PAGES_PIPELINE
    assert "steps" not in pages
    assert pages["with"] == {
        "content_source": "docs",
        "shared_theme_enabled": True,
    }
    assert pages["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }
    release = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    for job in release["jobs"].values():
        for step in job.get("steps", []):
            action = step.get("uses")
            if action:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action)


def test_every_release_job_using_uvx_installs_uv_first() -> None:
    document = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))

    for name, job in document["jobs"].items():
        steps = job.get("steps", [])
        commands = "\n".join(str(step.get("run", "")) for step in steps)
        if "uvx " not in commands:
            continue
        setup_positions = [
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith(UV_ACTION)
        ]
        uvx_positions = [
            index
            for index, step in enumerate(steps)
            if "uvx " in str(step.get("run", ""))
        ]
        assert setup_positions, f"{name} uses uvx without setup-uv"
        assert min(setup_positions) < min(uvx_positions)


def test_release_uses_the_relocated_shared_gate_configuration_at_main() -> None:
    config_path = ROOT / ".config" / "pre-commit.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    shared = next(
        item
        for item in config["repos"]
        if item.get("repo") == "https://github.com/Knuckles-Team/pipelines"
    )
    workflow = RELEASE.read_text(encoding="utf-8")

    assert shared["rev"] == "main"
    for line in workflow.splitlines():
        if "pre-commit run" in line:
            assert "--config .config/pre-commit.yaml" in line


def test_release_uses_the_published_eg_wheel_without_a_source_overlay() -> None:
    document = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    gates = document["jobs"]["gates"]
    steps = gates["steps"]
    commands = [str(step.get("run", "")) for step in steps]

    assert "PYTHONPATH" not in gates.get("env", {})
    assert not any(
        step.get("with", {}).get("repository") == "Knuckles-Team/epistemic-graph"
        for step in steps
    )
    lock = commands.index("uv lock --check --no-sources")
    sync = commands.index(
        "uv sync --locked --no-sources --no-build-package epistemic-graph"
    )
    contract = commands.index(
        "env -u PYTHONPATH uv run --locked --no-sources "
        "python scripts/check_eg_release_dependency.py"
    )
    tests = next(
        i for i, command in enumerate(commands) if "python -m pytest -q" in command
    )
    types = next(i for i, command in enumerate(commands) if "python -m mypy" in command)
    assert lock < sync < contract < tests < types
    assert "env -u PYTHONPATH" in commands[tests]
    assert "env -u PYTHONPATH" in commands[types]


def test_published_eg_wheel_contract_rejects_stale_or_local_lock() -> None:
    project = {"project": {"dependencies": ["epistemic-graph>=2.27.0,<3"]}}
    root = {
        "name": "agent-connector-sdk",
        "metadata": {
            "requires-dist": [{"name": "epistemic-graph", "specifier": ">=2.27.0,<3"}]
        },
    }
    wheel = {
        "name": "epistemic-graph",
        "version": "2.27.0",
        "source": {"registry": "https://pypi.org/simple"},
        "wheels": [
            {
                "url": "https://files.pythonhosted.org/packages/eg-2.27.0.whl",
                "hash": "sha256:" + "a" * 64,
            }
        ],
    }
    require_lock_contract(project, {"package": [root, wheel]})

    with pytest.raises(ValueError, match="stale EG requirement"):
        require_lock_contract(
            project,
            {
                "package": [
                    {
                        **root,
                        "metadata": {
                            "requires-dist": [
                                {"name": "epistemic-graph", "specifier": ">=2.23.0,<3"}
                            ]
                        },
                    },
                    wheel,
                ]
            },
        )
    with pytest.raises(ValueError, match=r"published 2\.27\.0 registry"):
        require_lock_contract(
            project,
            {"package": [root, {**wheel, "source": {"path": "../epistemic-graph"}}]},
        )


def test_published_eg_error_catalog_requires_auth_codes_and_valid_rows() -> None:
    rows = [
        {
            "code": code,
            "class": "auth",
            "retryable": False,
            "http_status_hint": 403,
        }
        for code in (
            "AUTH_TENANT_MISMATCH",
            "AUTH_AUDIENCE_MISMATCH",
            "AUTH_POLICY_VERSION_MISMATCH",
        )
    ]
    require_error_catalog({"contract_version": 1, "errors": rows})

    with pytest.raises(ValueError, match="lacks auth boundary codes"):
        require_error_catalog({"contract_version": 1, "errors": rows[:-1]})
    with pytest.raises(ValueError, match="lacks auth boundary codes"):
        require_error_catalog(
            {
                "contract_version": 1,
                "errors": [rows[0], rows[1], {**rows[2], "class": "server"}],
            }
        )
    with pytest.raises(ValueError, match="duplicate/invalid codes"):
        require_error_catalog({"contract_version": 1, "errors": rows + rows[:1]})
    with pytest.raises(ValueError, match="invalid HTTP hint"):
        require_error_catalog(
            {"contract_version": 1, "errors": [{**rows[0], "http_status_hint": True}]}
        )
