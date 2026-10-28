"""Static contract for the forward-only old distribution release."""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from configparser import ConfigParser
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "compat" / "agent-connector-sdk"


def _project(path: Path) -> dict[str, object]:
    document = tomllib.loads((path / "pyproject.toml").read_text(encoding="utf-8"))
    return cast(dict[str, object], document["project"])


@pytest.mark.spec("SDK-QUALITY-RELEASE-R003")
def test_old_distribution_is_a_version_matched_metadata_forwarder() -> None:
    target = _project(ROOT)
    alias = _project(COMPAT)
    version = target["version"]
    assert alias["name"] == "agent-connector-sdk"
    assert target["name"] == "scion-sdk"
    assert alias["version"] == version
    assert alias["dependencies"] == [f"scion-sdk=={version}"]
    assert set(alias["optional-dependencies"]) == set(target["optional-dependencies"])
    for extra in target["optional-dependencies"]:
        assert alias["optional-dependencies"][extra] == [
            f"scion-sdk[{extra}]=={version}"
        ]


@pytest.mark.spec("SDK-QUALITY-RELEASE-R003")
def test_old_distribution_declares_no_payload_or_entry_points() -> None:
    alias = _project(COMPAT)
    assert "scripts" not in alias
    assert "entry-points" not in alias
    setuptools = tomllib.loads((COMPAT / "pyproject.toml").read_text(encoding="utf-8"))[
        "tool"
    ]["setuptools"]
    assert setuptools["packages"] == []
    assert setuptools["py-modules"] == []
    assert {
        path.relative_to(COMPAT) for path in COMPAT.rglob("*") if path.is_file()
    } == {Path("pyproject.toml"), Path("README.md")}


@pytest.mark.spec("SDK-QUALITY-RELEASE-R003")
def test_next_bump_updates_the_forwarder_version_with_the_target() -> None:
    config = ConfigParser()
    config.read(ROOT / ".bumpversion.cfg")
    section = "bumpversion:file:compat/agent-connector-sdk/pyproject.toml"
    assert config["bumpversion"]["current_version"] == _project(ROOT)["version"]
    assert config[section]["search"] == "{current_version}"
    assert config[section]["replace"] == "{new_version}"


def test_bump_updates_all_compatibility_dependency_pins(tmp_path: Path) -> None:
    executable = shutil.which("bump2version")
    if executable is None:
        pytest.skip("bump2version CLI is not installed")
    compat = tmp_path / "compat" / "agent-connector-sdk"
    compat.mkdir(parents=True)
    for source, target in (
        (ROOT / ".bumpversion.cfg", tmp_path / ".bumpversion.cfg"),
        (ROOT / "pyproject.toml", tmp_path / "pyproject.toml"),
        (ROOT / "uv.lock", tmp_path / "uv.lock"),
        (COMPAT / "README.md", compat / "README.md"),
        (COMPAT / "pyproject.toml", compat / "pyproject.toml"),
    ):
        shutil.copy2(source, target)
    subprocess.run(
        [
            executable,
            "patch",
            "--new-version",
            "99.99.99",
            "--allow-dirty",
            "--no-commit",
            "--no-tag",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    lock = tomllib.loads((tmp_path / "uv.lock").read_text())
    target = next(
        package for package in lock["package"] if package["name"] == "scion-sdk"
    )
    assert target["version"] == "99.99.99"
    assert "VERSION=99.99.99" in (compat / "README.md").read_text()
    alias = _project(compat)
    assert _project(tmp_path)["version"] == alias["version"] == "99.99.99"
    assert alias["dependencies"] == ["scion-sdk==99.99.99"]
    for extra, requirements in alias["optional-dependencies"].items():
        assert requirements == [f"scion-sdk[{extra}]==99.99.99"]


@pytest.mark.spec("SDK-QUALITY-RELEASE-R003")
def test_upgrade_guidance_requires_payload_safe_recovery_and_verification() -> None:
    guidance = (COMPAT / "README.md").read_text(encoding="utf-8")
    assert "Do not" in guidance
    assert "python -m pip install --upgrade agent-connector-sdk" in guidance
    assert "python -m pip uninstall -y agent-connector-sdk" in guidance
    assert (
        'python -m pip install "scion-sdk==$VERSION" "agent-connector-sdk==$VERSION"'
        in guidance
    )
    assert 'python -m pip install --upgrade "agent-connector-sdk==$VERSION"' in guidance
    assert (
        'python -m pip install --force-reinstall --no-deps "scion-sdk==$VERSION"'
        in guidance
    )
    assert "import agent_connector_sdk" in guidance
    assert "from importlib import metadata, resources" in guidance
    assert "scion-sdk" in guidance and "agent-connector-sdk" in guidance
    assert "python -m pip check" in guidance
