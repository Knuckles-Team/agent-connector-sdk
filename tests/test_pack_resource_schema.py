"""SCION-CONNECTOR-CONTROL-R075.7: the declaration entry carries its content schema."""

from __future__ import annotations

import json

import pytest
from epistemic_graph.generated.connector_pack import PackEntryKind

from agent_connector_sdk.artifacts.pack import build_content_pack
from agent_connector_sdk.artifacts.prompts import PromptArtifactKind
from agent_connector_sdk.artifacts.resources import ResourceArtifactKind
from agent_connector_sdk.artifacts.skills import SkillArtifactKind
from agent_connector_sdk.artifacts.tools import ToolArtifactKind
from agent_connector_sdk.ingest.sources import IngestSourceDeclaration
from agent_connector_sdk.testing.results import SessionFactory

KINDS = (
    ToolArtifactKind(),
    SkillArtifactKind(),
    PromptArtifactKind(),
    ResourceArtifactKind(),
)


def _section(data: bytes, ref: object) -> bytes:
    return data[ref.offset : ref.offset + ref.length]  # type: ignore[attr-defined]


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R075.7")
async def test_pack_satisfies_engine_resource_schema_rule(
    sessions: SessionFactory,
) -> None:
    """Mirror of EG ``validate_mcp_schemas``: a resource needs a content schema."""
    async with sessions() as session:
        pack = await build_content_pack(session, connector="demo-agent", kinds=KINDS)
    resources = [e for e in pack.archive.entries if e.kind is PackEntryKind.RESOURCE]
    assert [e.uri for e in resources] == ["connector://resources"]
    for entry in pack.archive.entries:
        if entry.kind is PackEntryKind.RESOURCE:
            assert entry.output_schema is not None, (
                "resource content schema is required"
            )
        if entry.kind is PackEntryKind.RESOURCE_TEMPLATE:
            assert entry.input_schema is not None
            assert entry.output_schema is not None
    declaration = resources[0]
    schema = json.loads(_section(pack.archive.data, declaration.output_schema))
    assert schema == IngestSourceDeclaration.model_json_schema()
    body = json.loads(_section(pack.archive.data, declaration.body))
    IngestSourceDeclaration.model_validate(body)
    assert set(schema["required"]) <= set(body)
