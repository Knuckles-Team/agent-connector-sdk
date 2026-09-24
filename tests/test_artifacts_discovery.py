"""Artifact kinds, content packs, the artifact conformance kit, and extension discovery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import mcp_types
import pytest
from epistemic_graph.generated.connector_pack import PackAnnotations

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
from agent_connector_sdk.manifest.tool_schema import canonical_output_schema
from agent_connector_sdk.mcp.content import ConnectorContent
from agent_connector_sdk.ports.artifact_kind import ArtifactKind
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.runner.provisioning import provision_connector_content
from agent_connector_sdk.sinks.epistemic_graph import EpistemicGraphSink
from agent_connector_sdk.testing.artifact_kinds import (
    check_artifact_kind,
    check_artifact_rejects_malformed,
    check_tool_contract_pin_normalization,
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


async def test_contract_pin_normalization_passes_for_a_real_tool(
    sessions: SessionFactory,
) -> None:
    """EH-199: the SDK TCK recomputes the D18 pin EG cannot recompute itself."""
    result = await check_tool_contract_pin_normalization(ToolArtifactKind(), sessions)
    assert result.passed, result.detail


async def test_contract_pin_normalization_catches_a_drifted_pin(
    sessions: SessionFactory,
) -> None:
    """Prove the check actually fires: a tampered pin must fail it."""
    async with sessions() as session:
        server = await session.server_identity()
        entries = await ToolArtifactKind().list_entries(session, server)
    tampered_annotations = entries[0].annotations.model_copy(
        update={"sdk_contract_pin": "0" * 64}
    )
    tampered = (
        entries[0].model_copy(update={"annotations": tampered_annotations}),
        *entries[1:],
    )

    class _TamperedToolKind:
        kind = "tool"

        async def list_entries(
            self, session: object, server: object
        ) -> tuple[CapturedArtifact, ...]:
            return tampered

        def validate(self, entry: CapturedArtifact) -> None:
            return None

    result = await check_tool_contract_pin_normalization(_TamperedToolKind(), sessions)
    assert not result.passed
    assert "recomputed D18 fingerprint" in result.detail


async def test_contract_pin_normalization_reports_an_empty_client_schema(
    sessions: SessionFactory,
) -> None:
    """EH-215's exact regression shape: no client-visible input schema fails
    the check with a clear reason instead of an uncaught exception."""
    broken_tool = mcp_types.Tool.model_validate({"name": "broken", "inputSchema": {}})
    fabricated = CapturedArtifact(
        kind="tool",
        uri="tool://demo-mcp/broken",
        name="broken",
        media_type="application/json",
        body="{}",
        server=SERVER,
        annotations=PackAnnotations(sdk_contract_pin="1" * 64),
    )

    class _BrokenSchemaSession:
        async def server_identity(self) -> ServerIdentity:
            return SERVER

        async def list_tools(self) -> list[Any]:
            return [broken_tool]

    class _FabricatedToolKind:
        kind = "tool"

        async def list_entries(
            self, session: object, server: object
        ) -> tuple[CapturedArtifact, ...]:
            return (fabricated,)

        def validate(self, entry: CapturedArtifact) -> None:
            return None

    @asynccontextmanager
    async def _broken_sessions() -> AsyncIterator[_BrokenSchemaSession]:
        yield _BrokenSchemaSession()

    result = await check_tool_contract_pin_normalization(
        _FabricatedToolKind(), _broken_sessions
    )
    assert not result.passed
    assert "no client-visible input schema" in result.detail


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


@pytest.mark.parametrize("declared_mode", ["condensed", "verbose"])
async def test_tool_mode_annotation_reaches_generated_pack(declared_mode: str) -> None:
    """EH-213: ``PackAnnotations.tool_mode`` (EG `feat/pack-complete` 33fccec61) is a
    connector-declared claim like every other ``eg.annotations`` field (RF §5.1's "the
    pack builder's declaration, EG never re-derives it" -- ``catalog_attributes.rs``'s
    own comment). It reaches the generated pack through the SAME generic
    ``_declared_annotations``/``PackAnnotations.model_validate`` path every other
    annotation uses, so no SDK code names the field explicitly -- this proves that
    generic path already targets the exact pack-complete shape with zero SDK changes.
    """
    tool = mcp_types.Tool.model_validate(
        {
            "name": "moded",
            "inputSchema": {"type": "object"},
            "_meta": {"eg.annotations": {"tool_mode": declared_mode}},
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
    assert annotations.tool_mode is not None
    assert annotations.tool_mode.value == declared_mode


async def _tool_pack_entry(tool: Any) -> Any:
    session = SimpleNamespace(
        server_identity=AsyncMock(return_value=SERVER),
        list_tools=AsyncMock(return_value=[tool]),
    )
    pack = await build_content_pack(
        session, connector="demo-agent", kinds=(ToolArtifactKind(),)
    )
    return pack.archive.entries[0]


async def test_the_output_schema_section_is_the_canonical_contract_form() -> None:
    """D18: EG's ``output_schema_digest`` is the sha256 of this section, so the
    section must be the SDK's canonical output schema: a reordered ``required``
    list is the same contract and the same digest."""
    output = {
        "type": "object",
        "properties": {"b": {"type": "string"}, "a": {"type": "integer"}},
        "required": ["b", "a"],
    }
    typed = mcp_types.Tool.model_validate(
        {"name": "out", "inputSchema": {"type": "object"}, "outputSchema": output}
    )
    reordered = mcp_types.Tool.model_validate(
        {
            "name": "out",
            "inputSchema": {"type": "object"},
            "outputSchema": {**output, "required": ["a", "b"]},
        }
    )
    first = await _tool_pack_entry(typed)
    second = await _tool_pack_entry(reordered)
    canonical = json.dumps(
        canonical_output_schema(typed),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    assert first.output_schema is not None and second.output_schema is not None
    assert first.output_schema.sha256 == hashlib.sha256(canonical).hexdigest()
    assert second.output_schema.sha256 == first.output_schema.sha256
    declares_none = await _tool_pack_entry(
        mcp_types.Tool.model_validate(
            {"name": "out", "inputSchema": {"type": "object"}}
        )
    )
    assert declares_none.output_schema is None


async def test_tool_mode_rejects_a_value_outside_the_generated_enum() -> None:
    tool = mcp_types.Tool.model_validate(
        {
            "name": "mismoded",
            "inputSchema": {"type": "object"},
            "_meta": {"eg.annotations": {"tool_mode": "both"}},
        }
    )
    session = SimpleNamespace(list_tools=AsyncMock(return_value=[tool]))
    with pytest.raises(MalformedArtifactError, match="eg\\.annotations is malformed"):
        await ToolArtifactKind().list_entries(session, SERVER)


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


async def test_tool_cost_and_latency_annotations_reach_generated_pack() -> None:
    tool = mcp_types.Tool.model_validate(
        {
            "name": "priced",
            "inputSchema": {"type": "object"},
            "_meta": {
                "eg.annotations": {
                    "cost": {"currency": "USD", "per_call_micros": 1200},
                    "latency_declared": {"p50_ms": 40, "p95_ms": 120},
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
    assert annotations.cost is not None
    assert annotations.cost.currency == "USD"
    assert annotations.latency_declared is not None
    assert annotations.latency_declared.p50_ms == 40
    assert annotations.latency_declared.p95_ms == 120


@pytest.mark.parametrize("currency", ["usd", "US", "USDD", "US1", "", "  USD"])
async def test_tool_cost_rejects_non_iso4217_currency(currency: str) -> None:
    tool = mcp_types.Tool.model_validate(
        {
            "name": "mispriced",
            "inputSchema": {"type": "object"},
            "_meta": {
                "eg.annotations": {"cost": {"currency": currency, "per_call_micros": 1}}
            },
        }
    )
    session = SimpleNamespace(list_tools=AsyncMock(return_value=[tool]))
    with pytest.raises(MalformedArtifactError, match="ISO-4217"):
        await ToolArtifactKind().list_entries(session, SERVER)


async def test_tool_latency_rejects_p50_above_p95() -> None:
    tool = mcp_types.Tool.model_validate(
        {
            "name": "backwards-latency",
            "inputSchema": {"type": "object"},
            "_meta": {
                "eg.annotations": {"latency_declared": {"p50_ms": 500, "p95_ms": 100}}
            },
        }
    )
    session = SimpleNamespace(list_tools=AsyncMock(return_value=[tool]))
    with pytest.raises(MalformedArtifactError, match="p50_ms"):
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
