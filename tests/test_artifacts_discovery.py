"""Artifact kinds, content packs, the artifact conformance kit, and extension discovery."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import mcp_types
import pytest

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.artifacts.common import (
    canonical_json,
    front_matter,
    json_object,
    mime_type,
    require_kind,
)
from agent_connector_sdk.artifacts.pack import build_content_pack
from agent_connector_sdk.artifacts.prompts import PromptArtifactKind
from agent_connector_sdk.artifacts.resources import (
    ResourceArtifactKind,
)
from agent_connector_sdk.artifacts.skills import SkillArtifactKind
from agent_connector_sdk.artifacts.tools import ToolArtifactKind
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.discovery import (
    ARTIFACT_KIND_GROUP,
    EXTENSION_GROUPS,
    SINK_GROUP,
    SOURCE_ADAPTER_GROUP,
    TRANSPORT_GROUP,
    ActivationPolicy,
    CertifiedExtensions,
    ExtensionActivationError,
    ExtensionDiscoveryError,
    ExtensionIdentity,
    discover_extensions,
    load_extension,
    sdk_reference_extensions,
)
from agent_connector_sdk.mcp.content import ConnectorContent
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.runner.provisioning import provision_connector_content
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.testing.artifact_kinds import (
    check_artifact_kind,
    check_artifact_rejects_malformed,
)
from agent_connector_sdk.testing.results import SessionFactory, assert_conformant
from agent_connector_sdk.testing.sinks import InMemorySink
from agent_connector_sdk.transports.mcp import McpTransport

SERVER = ServerIdentity(name="demo-mcp", version="1.4.0")
KINDS: tuple[ArtifactKind, ...] = (
    ToolArtifactKind(),
    SkillArtifactKind(),
    PromptArtifactKind(),
    ResourceArtifactKind(),
)


def _entry(kind: str, uri: str, body: str, name: str = "demo") -> CapturedArtifact:
    return CapturedArtifact(
        kind=kind, uri=uri, name=name, media_type="text/plain", body=body, server=SERVER
    )


MALFORMED = {
    "tool": _entry(
        "tool", "tool://demo-mcp/demo", '{"name": "demo", "input_schema": []}'
    ),
    "skill": _entry("skill", "skill://demo/SKILL.md", "# no front matter"),
    "prompt": _entry(
        "prompt", "prompt://demo-mcp/demo", '{"name": "demo", "arguments": [{}]}'
    ),
    "resource": _entry("resource", "mystery://demo-agent/x", "body"),
}


@pytest.mark.parametrize("kind", KINDS, ids=lambda kind: kind.kind)
async def test_artifact_kinds_pass_the_conformance_kit(
    kind: ArtifactKind, sessions: SessionFactory
) -> None:
    assert isinstance(kind, ArtifactKind)
    assert_conformant(await check_artifact_kind(kind, sessions))
    assert check_artifact_rejects_malformed(kind, MALFORMED[kind.kind]).passed
    assert (
        check_artifact_rejects_malformed(kind, _entry("other", "x://y", "{}")).passed
        is not False
    )


async def test_content_pack_is_complete_and_stable(sessions: SessionFactory) -> None:
    async with sessions() as session:
        pack = await build_content_pack(session, connector="demo-agent", kinds=KINDS)
    async with sessions() as session:
        again = await build_content_pack(session, connector="demo-agent", kinds=KINDS)
    uris = sorted(entry.uri for entry in pack.archive.entries)
    assert uris == [
        "manifest://connector",
        "ontology://demo-agent/demo.ttl",
        "prompt://demo-mcp/demo_agent",
        "shapes://demo-agent/demo.shapes.ttl",
        "skill://demo-reader/SKILL.md",
        "tool://demo-mcp/demo_reader",
    ]
    assert pack.archive == again.archive
    assert {entry.kind.value for entry in pack.archive.entries} >= {
        "manifest",
        "ontology",
        "shapes",
    }


async def test_shape_resource_bytes_reach_generated_archive_unchanged(
    sessions: SessionFactory, package_root: Path
) -> None:
    """Canonical connector Turtle reaches the generated archive unchanged."""
    shape_path = package_root / "ontology" / "shapes" / "demo.shapes.ttl"
    expected = shape_path.read_bytes()
    async with sessions() as session:
        pack = await build_content_pack(
            session, connector="demo-agent", kinds=(ResourceArtifactKind(),)
        )

    shape = next(
        entry
        for entry in pack.archive.entries
        if entry.uri == "shapes://demo-agent/demo.shapes.ttl"
    )
    body = pack.archive.data[shape.body.offset : shape.body.offset + shape.body.length]
    assert shape.kind.value == "shapes"
    assert shape.name == shape.uri
    assert shape.media_type == "text/turtle"
    assert body == expected
    assert shape.body.sha256 == hashlib.sha256(expected).hexdigest()


async def test_declared_content_providers_import_as_separate_pack_heads(
    tmp_path: Path,
) -> None:
    providers: list[ConnectorContent] = []
    for connector, file_name, body in (
        (
            "agent-utilities",
            "governance.shapes.ttl",
            b"@prefix sh: <urn:sh:> .\n<urn:au> a sh:NodeShape .\n",
        ),
        (
            "graph-os",
            "runtime.shapes.ttl",
            b"@prefix sh: <urn:sh:> .\n<urn:os> a sh:NodeShape .\n",
        ),
    ):
        root = tmp_path / connector
        shapes = root / "ontology" / "shapes"
        shapes.mkdir(parents=True)
        (shapes / file_name).write_bytes(body)
        providers.append(
            ConnectorContent(
                connector=connector,
                package_root=root,
                package_version="1.0.0",
            )
        )

    sink = InMemorySink()
    outcomes = [
        await provision_connector_content(provider, sink=sink) for provider in providers
    ]

    assert all(outcome.changed for outcome in outcomes)
    assert len(sink.packs) == 2
    packs = {pack.connector: pack for pack in sink.packs.values()}
    assert set(packs) == {"agent-utilities", "graph-os"}
    expected_names = {
        "agent-utilities": "governance.shapes.ttl",
        "graph-os": "runtime.shapes.ttl",
    }
    for connector, pack in packs.items():
        assert pack.archive.server.uri == f"mcp-server://{connector}"
        assert [entry.uri for entry in pack.archive.entries] == [
            f"shapes://{connector}/{expected_names[connector]}"
        ]


async def test_content_pack_rejects_duplicate_uris(sessions: SessionFactory) -> None:
    async with sessions() as session:
        with pytest.raises(MalformedArtifactError):
            await build_content_pack(
                session,
                connector="demo-agent",
                kinds=(ToolArtifactKind(), ToolArtifactKind()),
            )


async def test_tool_annotations_and_certified_pin_reach_generated_pack() -> None:
    tool = mcp_types.Tool.model_validate(
        {
            "name": "annotated",
            "description": "fixture",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
            "_meta": {
                "eg.annotations": {
                    "provides": ["eg:capability/annotated"],
                    "modalities_in": ["eg:modality/text"],
                    "contract_version": "1.2.3",
                }
            },
        }
    )
    session = SimpleNamespace(
        server_identity=AsyncMock(return_value=SERVER),
        list_tools=AsyncMock(return_value=[tool]),
    )
    pack = await build_content_pack(
        session, connector="demo-agent", kinds=(ToolArtifactKind(),)
    )
    annotations = pack.archive.entries[0].annotations
    assert annotations is not None
    assert annotations.provides == ["eg:capability/annotated"]
    assert annotations.modalities_in == ["eg:modality/text"]
    assert annotations.contract_version == "1.2.3"
    assert annotations.read_only_hint is True
    assert annotations.open_world_hint is False
    assert len(annotations.sdk_contract_pin) == 64


async def test_tool_annotation_conflict_fails_closed() -> None:
    tool = mcp_types.Tool.model_validate(
        {
            "name": "ambiguous",
            "inputSchema": {"type": "object"},
            "annotations": {"readOnlyHint": True},
            "_meta": {"eg.annotations": {"read_only_hint": False}},
        }
    )
    session = SimpleNamespace(list_tools=AsyncMock(return_value=[tool]))
    with pytest.raises(MalformedArtifactError, match="conflicting pack annotation"):
        await ToolArtifactKind().list_entries(session, SERVER)


async def test_skill_front_matter_annotations_reach_generated_pack() -> None:
    body = """---
name: annotated-skill
description: fixture
eg.annotations:
  provides: [eg:capability/skill]
  modalities_out: [eg:modality/text]
---
body
"""
    resource = SimpleNamespace(
        uri="skill://annotated-skill/SKILL.md", mimeType="text/markdown"
    )
    session = SimpleNamespace(
        server_identity=AsyncMock(return_value=SERVER),
        list_resources=AsyncMock(return_value=[resource]),
        read_resource=AsyncMock(return_value=body),
    )
    pack = await build_content_pack(
        session, connector="demo-agent", kinds=(SkillArtifactKind(),)
    )
    annotations = pack.archive.entries[0].annotations
    assert annotations is not None
    assert annotations.provides == ["eg:capability/skill"]
    assert annotations.modalities_out == ["eg:modality/text"]


def test_artifact_helpers() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert front_matter("---\nname: x\n---\nbody") == {"name": "x"}
    assert front_matter("no front matter") is None
    assert front_matter("---\n: [\n---\n") is None
    assert mime_type(SimpleNamespace(mimeType="text/turtle"), "d") == "text/turtle"
    assert mime_type(SimpleNamespace(), "d") == "d"
    with pytest.raises(MalformedArtifactError):
        json_object(_entry("tool", "tool://x/y", "[]"))
    with pytest.raises(MalformedArtifactError):
        require_kind(_entry("tool", "tool://x/y", "{}"), "skill")
    with pytest.raises(MalformedArtifactError):
        ResourceArtifactKind().validate(
            _entry("resource", "manifest://connector", "connector: [bad")
        )
    with pytest.raises(MalformedArtifactError):
        ResourceArtifactKind().validate(
            _entry("resource", "a2a-card://demo/card", "[]")
        )


def test_reference_extensions_are_discoverable_and_certified() -> None:
    policy: ActivationPolicy = sdk_reference_extensions()
    assert set(EXTENSION_GROUPS) == {
        SOURCE_ADAPTER_GROUP,
        ARTIFACT_KIND_GROUP,
        TRANSPORT_GROUP,
        SINK_GROUP,
    }
    kinds = discover_extensions(ARTIFACT_KIND_GROUP)
    assert [identity.name for identity in kinds] == [
        "prompts",
        "resources",
        "skills",
        "tools",
    ]
    assert all(
        isinstance(identity, ExtensionIdentity) and policy.authorizes(identity)
        for identity in kinds
    )
    assert (
        load_extension(SOURCE_ADAPTER_GROUP, "mcp_tool", policy=policy)
        is McpToolSourceAdapter
    )
    assert load_extension(TRANSPORT_GROUP, "mcp", policy=policy) is McpTransport
    assert (
        load_extension(SINK_GROUP, "epistemic_graph", policy=policy)
        is EpistemicGraphSink
    )
    for identity in kinds:
        loaded = load_extension(ARTIFACT_KIND_GROUP, identity.name, policy=policy)
        assert isinstance(loaded, type) and isinstance(loaded(), ArtifactKind)


def test_activation_fails_closed() -> None:
    with pytest.raises(ExtensionActivationError):
        load_extension(SOURCE_ADAPTER_GROUP, "mcp_tool", policy=CertifiedExtensions([]))
    with pytest.raises(LookupError):
        load_extension(
            SOURCE_ADAPTER_GROUP, "unknown", policy=sdk_reference_extensions()
        )
    with pytest.raises(ValueError):
        discover_extensions("agent_connector_sdk.unknown")


def test_discovery_rejects_ambiguous_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def entry(dist_name: str | None) -> SimpleNamespace:
        dist = (
            None
            if dist_name is None
            else SimpleNamespace(metadata={"Name": dist_name}, version="1.0")
        )
        return SimpleNamespace(name="dup", value="pkg:Adapter", dist=dist)

    monkeypatch.setattr(
        "agent_connector_sdk.discovery.entry_points",
        lambda group: [entry("one"), entry("two")],
    )
    with pytest.raises(ExtensionDiscoveryError, match="declared by both"):
        discover_extensions(SOURCE_ADAPTER_GROUP)
    monkeypatch.setattr(
        "agent_connector_sdk.discovery.entry_points", lambda group: [entry(None)]
    )
    with pytest.raises(ExtensionDiscoveryError, match="no distribution"):
        discover_extensions(SOURCE_ADAPTER_GROUP)
