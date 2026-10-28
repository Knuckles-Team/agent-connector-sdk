"""Prompt role and targets survive a live MCP capture into the engine pack."""

import json

import pytest
from epistemic_graph.generated.connector_pack import PackEntryKind

from agent_connector_sdk.artifacts.pack import build_connector_content_pack
from agent_connector_sdk.mcp.content import ConnectorContent, ContentError


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R074.2")
async def test_prompt_role_and_concepts_reach_the_pack_entry(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for name, declaration in {
        "system": {
            "role": "system",
            "ontology_class": "https://example.org/Item",
            "identity": {"role": "Specialist"},
        },
        "default": {"serves": ["https://example.org/capability"]},
        "template": {"role": "template"},
    }.items():
        declaration["instructions"] = {"core_directive": "Read records."}
        (prompts / f"{name}.json").write_text(json.dumps(declaration))
    pack = await build_connector_content_pack(
        ConnectorContent("demo-agent", tmp_path, "1.0")
    )
    bodies = {}
    for entry in pack.archive.entries:
        if entry.kind is PackEntryKind.PROMPT:
            ref = entry.body
            bodies[entry.name] = json.loads(
                pack.archive.data[ref.offset : ref.offset + ref.length]
            )
    assert bodies["system"]["role"] == "system"
    assert bodies["system"]["serves"] == "https://example.org/Item"
    assert (
        bodies["system"]["definition"]["_meta"]["team.knuckles/prompt"]["role"]
        == "Specialist"
    )
    assert bodies["default"]["role"] == "task"
    assert bodies["default"]["serves"] == ["https://example.org/capability"]
    assert bodies["template"]["role"] == "template"


async def test_prompt_role_rejects_unknown_role(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "bad.json").write_text(
        json.dumps({"role": "admin", "instructions": {"core_directive": "Read."}})
    )
    with pytest.raises(ContentError, match="prompt role"):
        await build_connector_content_pack(
            ConnectorContent("demo-agent", tmp_path, "1.0")
        )
