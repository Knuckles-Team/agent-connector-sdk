"""SCION-CONNECTOR-CONTROL-R075.7: the SDK imports and packs against the EG floor.

A fresh install resolves the lowest ``medulla`` the SDK declares. Every
SDK module must import against it, and every pack entry kind the SDK maps must
exist in its generated ``PackEntryKind``.
"""

from __future__ import annotations

import importlib
import pkgutil
import tomllib
from importlib import metadata
from pathlib import Path

import pytest
from epistemic_graph.generated.connector_pack import PackEntryKind
from packaging.requirements import Requirement
from packaging.version import Version

import scion_sdk
from scion_sdk.artifacts import pack as pack_module
from scion_sdk.artifacts.pack import build_content_pack
from scion_sdk.artifacts.prompts import PromptArtifactKind
from scion_sdk.artifacts.resources import ResourceArtifactKind
from scion_sdk.artifacts.skills import SkillArtifactKind
from scion_sdk.artifacts.tools import ToolArtifactKind
from scion_sdk.contracts import CapturedArtifact, ServerIdentity
from scion_sdk.ports.errors import MalformedArtifactError
from scion_sdk.testing.results import SessionFactory

ROOT = Path(__file__).resolve().parent.parent
EG_FLOOR = Version("2.27.10")


def _declared_eg_requirement() -> Requirement:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for line in project["project"]["dependencies"]:
        requirement = Requirement(line)
        if requirement.name == "medulla":
            return requirement
    raise AssertionError("pyproject.toml declares no medulla dependency")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R075.7")
def test_tested_engine_is_the_declared_floor_or_newer() -> None:
    requirement = _declared_eg_requirement()
    assert min(Version(s.version) for s in requirement.specifier) == EG_FLOOR
    installed = Version(metadata.version("medulla"))
    assert installed >= EG_FLOOR
    assert installed in requirement.specifier


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R075.7")
def test_every_sdk_module_imports_against_the_engine() -> None:
    names = [
        info.name
        for info in pkgutil.walk_packages(scion_sdk.__path__, prefix="scion_sdk.")
    ]
    assert "scion_sdk.artifacts.pack" in names
    assert "scion_sdk.ports.sink" in names
    for name in names:
        importlib.import_module(name)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R075.7")
def test_every_mapped_entry_kind_exists_in_the_engine() -> None:
    mapped = {*pack_module._RESOURCE_KINDS.values(), *pack_module._KINDS.values()}
    assert mapped <= set(PackEntryKind)
    assert set(pack_module._RESOURCE_KINDS) == {
        "ui",
        "ontology",
        "shapes",
        "model-profile",
        "a2a-card",
        "data",
    }
    assert not hasattr(PackEntryKind, "MANIFEST")


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R075.7")
def test_a_manifest_resource_has_no_pack_entry_kind() -> None:
    entry = CapturedArtifact(
        kind="resource",
        uri="manifest://demo-agent",
        name="manifest",
        media_type="application/yaml",
        body="{}",
        server=ServerIdentity(name="demo-agent", version="1.0.0"),
    )
    with pytest.raises(MalformedArtifactError, match="no ConnectorPack entry kind"):
        pack_module._entry_content(entry)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R075.7")
async def test_a_pack_builds_against_the_engine(sessions: SessionFactory) -> None:
    kinds = (
        ToolArtifactKind(),
        SkillArtifactKind(),
        PromptArtifactKind(),
        ResourceArtifactKind(),
    )
    async with sessions() as session:
        pack = await build_content_pack(session, connector="demo-agent", kinds=kinds)
    entry_kinds = {entry.kind for entry in pack.archive.entries}
    assert {PackEntryKind.TOOL, PackEntryKind.RESOURCE} <= entry_kinds
    assert entry_kinds <= set(PackEntryKind)
    assert pack.archive.server.kind is PackEntryKind.MCP_SERVER
