"""The public tool-body estimate follows the canonical capture."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent_connector_sdk.artifacts.tool_facts import (
    DEFAULT_SCHEMA_BYTES_PER_TOKEN,
    SideEffect,
    ToolContractFacts,
    facts_from_declaration,
    schema_tokens,
)
from agent_connector_sdk.artifacts.tools import _tool_entry
from agent_connector_sdk.contracts import ServerIdentity


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R045.3")
def test_schema_tokens_uses_canonical_body_and_named_divisor() -> None:
    assert DEFAULT_SCHEMA_BYTES_PER_TOKEN == 4
    assert [schema_tokens("x" * n) for n in range(9)] == [0, 1, 1, 1, 1, 2, 2, 2, 2]
    assert schema_tokens("ééé") == 2
    tool = SimpleNamespace(
        name="read",
        description="résumé",
        inputSchema={"type": "object", "properties": {}},
        output_schema=None,
        annotations=None,
    )
    entry = _tool_entry(tool, ServerIdentity(name="example", version="1"))
    assert "r\\u00e9sum\\u00e9" in entry.body
    assert schema_tokens(entry.body) == (len(entry.body.encode("utf-8")) + 3) // 4


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R045.1")
def test_facts_model_is_frozen_and_typed() -> None:
    facts = ToolContractFacts(
        read_only=True,
        side_effects=frozenset({SideEffect.NETWORK}),
        arg_schema={"type": "object"},
        schema_tokens=3,
        declared_by="connector",
    )
    assert facts.side_effects == frozenset({SideEffect.NETWORK})
    assert facts.arg_schema == {"type": "object"}
    with pytest.raises(ValidationError):
        facts.read_only = False
    with pytest.raises(ValidationError):
        ToolContractFacts.model_validate(
            {**facts.model_dump(), "declared_by": "unknown"}
        )


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R045.2")
def test_side_effect_set_is_closed_and_read_only_is_consistent() -> None:
    assert {effect.value for effect in SideEffect} == {
        "none",
        "workspace_write",
        "external_write",
        "network",
    }
    base = {
        "read_only": True,
        "arg_schema": {},
        "schema_tokens": 0,
        "declared_by": "connector",
    }
    for effects in (
        {"workspace_write"},
        {"external_write"},
        {"none", "network"},
        {"other"},
    ):
        with pytest.raises(ValidationError):
            ToolContractFacts.model_validate({**base, "side_effects": effects})
    assert ToolContractFacts.model_validate(
        {**base, "side_effects": {"none"}}
    ).read_only
    assert not ToolContractFacts.model_validate(
        {**base, "read_only": False, "side_effects": {"external_write", "network"}}
    ).read_only


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R045.4")
def test_undeclared_tool_defaults_to_not_read_only() -> None:
    tool = SimpleNamespace(
        name="read_users", inputSchema={"type": "object"}, annotations=None
    )
    facts = facts_from_declaration(tool)
    assert not facts.read_only
    assert facts.side_effects == {SideEffect.EXTERNAL_WRITE}
    assert facts.declared_by == "default"
    entry = _tool_entry(tool, ServerIdentity(name="example", version="1"))
    assert facts.schema_tokens == schema_tokens(entry.body)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R045.5")
def test_mcp_read_only_hint_is_recorded_as_self_declared() -> None:
    from agent_connector_sdk.ports.errors import MalformedArtifactError

    tool = SimpleNamespace(
        name="write",
        inputSchema={"type": "object"},
        annotations={"readOnlyHint": True},
        meta=None,
    )
    facts = facts_from_declaration(tool)
    assert facts.read_only and facts.declared_by == "mcp_hint"
    assert not facts.side_effects
    declared = facts_from_declaration(
        {
            "name": "query",
            "inputSchema": {"type": "object"},
            "_meta": {"eg.annotations": {"read_only_hint": True}},
        }
    )
    assert declared.read_only and declared.declared_by == "connector"
    tool.meta = {"eg.annotations": {"read_only_hint": False}}
    with pytest.raises(MalformedArtifactError, match="conflicting"):
        facts_from_declaration(tool)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R045.7")
def test_destructive_action_is_never_read_only() -> None:
    tool = {
        "name": "delete_user",
        "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True},
    }
    facts = facts_from_declaration(tool)
    assert not facts.read_only and SideEffect.EXTERNAL_WRITE in facts.side_effects
    assert facts.declared_by == "mcp_hint"
    exempt = facts_from_declaration(tool, operation={"destructive": False})
    assert exempt.read_only
    safe_name = {**tool, "name": "list_users"}
    explicit = facts_from_declaration(safe_name, operation={"destructive": True})
    assert not explicit.read_only and SideEffect.EXTERNAL_WRITE in explicit.side_effects
