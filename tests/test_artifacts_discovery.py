"""Artifact kinds, content packs, the artifact conformance kit, and extension discovery."""

from __future__ import annotations

from types import SimpleNamespace

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
    RESOURCE_RECORD_KINDS,
    ResourceArtifactKind,
)
from agent_connector_sdk.artifacts.skills import SkillArtifactKind
from agent_connector_sdk.artifacts.tools import ToolArtifactKind
from agent_connector_sdk.contracts import ArtifactEntry, ServerIdentity
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
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.testing.artifact_kinds import (
    check_artifact_kind,
    check_artifact_rejects_malformed,
)
from agent_connector_sdk.testing.results import SessionFactory, assert_conformant
from agent_connector_sdk.transports.mcp import McpTransport

SERVER = ServerIdentity(name="demo-mcp", version="1.4.0")
KINDS: tuple[ArtifactKind, ...] = (
    ToolArtifactKind(),
    SkillArtifactKind(),
    PromptArtifactKind(),
    ResourceArtifactKind(),
)


def _entry(kind: str, uri: str, body: str, name: str = "demo") -> ArtifactEntry:
    return ArtifactEntry(
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
    uris = sorted(entry.uri for entry in pack.entries)
    assert uris == [
        "manifest://connector",
        "ontology://demo-agent/demo.ttl",
        "prompt://demo-mcp/demo_agent",
        "shapes://demo-agent/demo.shapes.ttl",
        "skill://demo-reader/SKILL.md",
        "tool://demo-mcp/demo_reader",
    ]
    assert pack.digest == again.digest
    records = {
        ResourceArtifactKind().to_record(e).record_kind
        for e in pack.entries
        if e.kind == "resource"
    }
    assert records == {
        RESOURCE_RECORD_KINDS[s] for s in ("manifest", "ontology", "shapes")
    }


async def test_content_pack_rejects_duplicate_uris(sessions: SessionFactory) -> None:
    async with sessions() as session:
        with pytest.raises(MalformedArtifactError):
            await build_content_pack(
                session,
                connector="demo-agent",
                kinds=(ToolArtifactKind(), ToolArtifactKind()),
            )


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
