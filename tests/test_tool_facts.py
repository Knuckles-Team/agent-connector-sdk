"""The public tool-body estimate follows the canonical capture."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent_connector_sdk.artifacts.tool_facts import (
    DEFAULT_SCHEMA_BYTES_PER_TOKEN,
    SideEffect,
    ToolContractFacts,
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
