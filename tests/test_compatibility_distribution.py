"""Static contract for the forward-only old distribution release."""

from __future__ import annotations

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
    assert alias["version"] == version == "0.5.8"
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
    assert config[section]["search"] == 'version = "{current_version}"'
    assert config[section]["replace"] == 'version = "{new_version}"'


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
