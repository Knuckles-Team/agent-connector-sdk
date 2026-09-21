"""Release workflow contracts that must remain executable on a clean runner."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
CCCC_REVISION = "d728759323be5d9977b7390a27133e8eaf481f26"
CONFIGURE_PAGES_REVISION = "45bfe0192ca1faeb007ade9deae92b16b8254a0d"


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
