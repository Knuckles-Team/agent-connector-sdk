"""The public tool-body estimate follows the canonical capture."""

from types import SimpleNamespace

import pytest

from agent_connector_sdk.artifacts.tool_facts import (
    DEFAULT_SCHEMA_BYTES_PER_TOKEN,
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
