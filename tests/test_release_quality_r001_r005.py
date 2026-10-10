"""Tests for the R001 isolated-consumer plan and R005 import-graph reproducibility helpers.

SDK-QUALITY-RELEASE-R001 and -R005 (see specs/SDK-QUALITY-RELEASE/requirements.md).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load(module_name: str):
    module_path = SCRIPTS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"{module_name}_under_test", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_graph = _load("check_import_graph_reproducibility")
_compat = _load("check_wheel_consumer_compatibility")

FIXTURE = _graph.FIXTURE
compute_import_graph = _graph.compute_import_graph
read_recorded_graph = _graph.read_recorded_graph
CompatibilityGateError = _compat.CompatibilityGateError
isolated_install_plan = _compat.isolated_install_plan
pinned_graph_client_requirement = _compat.pinned_graph_client_requirement


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_pinned_graph_client_requirement_reads_the_declared_dependency() -> None:
    requirement = pinned_graph_client_requirement()
    assert requirement.startswith("epistemic-graph")
    assert any(op in requirement for op in (">=", "==", "~="))


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_pinned_graph_client_requirement_fails_closed_without_a_dependency() -> None:
    with pytest.raises(CompatibilityGateError):
        pinned_graph_client_requirement('[project]\nname = "x"\ndependencies = []\n')


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_isolated_install_plan_never_installs_from_the_source_overlay() -> None:
    plan = isolated_install_plan(
        Path("dist/agent_connector_sdk-1.0.0-py3-none-any.whl"),
        "epistemic-graph>=2.27.0,<3",
        Path("dist-consumer-venv"),
    )
    flat = [" ".join(command) for command in plan]
    assert any(cmd.startswith("uv venv") for cmd in flat)
    install_commands = [cmd for cmd in flat if "pip install" in cmd]
    assert install_commands, "plan must install the built wheel into the isolated venv"
    for command in install_commands:
        assert "-e ." not in command
        assert "agent_connector_sdk-1.0.0-py3-none-any.whl" in command
        assert "epistemic-graph>=2.27.0,<3" in command
        assert "--python dist-consumer-venv" in command


@pytest.mark.spec("SDK-QUALITY-RELEASE-R001")
def test_isolated_install_plan_rejects_a_non_wheel_path() -> None:
    with pytest.raises(CompatibilityGateError):
        isolated_install_plan(
            Path("dist/not-a-wheel.tar.gz"), "epistemic-graph>=2.27.0,<3", Path("venv")
        )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_local_pinned_install_reproduces_hosted_import_graph() -> None:
    """The exact import graph computed under this pinned environment must
    equal the recorded graph committed from an equivalently pinned
    (`uv sync --frozen`) resolve, proving local verification never drifts
    from the hosted release check without a visible, reviewable diff."""
    assert FIXTURE.exists(), "tests/fixtures/pinned_import_graph.txt must be committed"
    recorded = read_recorded_graph()
    live = compute_import_graph()
    assert live == recorded, (
        "local import graph drifted from the recorded hosted result; "
        "re-run scripts/check_import_graph_reproducibility.py --record under uv run --frozen"
    )


@pytest.mark.spec("SDK-QUALITY-RELEASE-R005")
def test_recorded_import_graph_is_sorted_and_deduplicated() -> None:
    recorded = read_recorded_graph()
    assert recorded == sorted(set(recorded))
    assert all("==" in entry for entry in recorded)
