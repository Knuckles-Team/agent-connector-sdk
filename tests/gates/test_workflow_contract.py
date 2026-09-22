"""Release workflow contracts that must remain executable on a clean runner."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
CCCC_REVISION = "d728759323be5d9977b7390a27133e8eaf481f26"
CONFIGURE_PAGES_REVISION = "45bfe0192ca1faeb007ade9deae92b16b8254a0d"
PIPELINES_REVISION = "7ae41925ca0a62c1fdb64197e0bb1859c1903a15"
EPISTEMIC_GRAPH_REVISION = "f17f47ab300f7f1ddd972d4e0214283a28547e36"
UV_ACTION = "astral-sh/setup-uv@"


def test_release_installs_cccc_1_6_from_its_immutable_upstream_commit() -> None:
    workflow = RELEASE.read_text(encoding="utf-8")

    assert "cargo install --locked --version 1.6.0" not in workflow
    assert "--git https://github.com/moznion/cccc" in workflow
    assert f"--rev {CCCC_REVISION}" in workflow


def test_pages_configures_the_site_before_uploading_the_artifact() -> None:
    workflow = PAGES.read_text(encoding="utf-8")
    configure = f"actions/configure-pages@{CONFIGURE_PAGES_REVISION}"

    assert configure in workflow
    assert workflow.index(configure) < workflow.index("actions/upload-pages-artifact@")
    assert "pages: write" in workflow
    assert "id-token: write" in workflow


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


def test_release_uses_the_relocated_pinned_shared_gate_configuration() -> None:
    config_path = ROOT / ".config" / "pre-commit.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    shared = next(
        item
        for item in config["repos"]
        if item.get("repo") == "https://github.com/Knuckles-Team/pipelines"
    )
    workflow = RELEASE.read_text(encoding="utf-8")

    assert shared["rev"] == PIPELINES_REVISION
    for line in workflow.splitlines():
        if "pre-commit run" in line:
            assert "--config .config/pre-commit.yaml" in line


def test_release_uses_the_finalized_generated_contract_source() -> None:
    document = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    gates = document["jobs"]["gates"]
    workflow = RELEASE.read_text(encoding="utf-8")

    assert gates["env"]["PYTHONPATH"].endswith("/.ci/epistemic-graph")
    assert f"ref: {EPISTEMIC_GRAPH_REVISION}" in workflow
    assert "uv sync --frozen --no-install-package epistemic-graph" in workflow
    assert "epistemic_graph.generated.source_ingestion" in workflow
