"""Full prompt capture through the MCP session, with honest failure semantics."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import mcp_types
import pytest

from agent_connector_sdk.artifacts.pack import build_content_pack
from agent_connector_sdk.artifacts.prompts import PromptArtifactKind
from agent_connector_sdk.artifacts.resources import ResourceArtifactKind
from agent_connector_sdk.artifacts.skills import SkillArtifactKind
from agent_connector_sdk.artifacts.tools import ToolArtifactKind
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.testing.results import SessionFactory
from agent_connector_sdk.transports.mcp_session import (
    McpPromptRejectedError,
    McpTransportError,
)

SERVER = ServerIdentity(name="demo-mcp", version="1.4.0")


async def test_whole_content_pack_retains_rendered_prompt(
    sessions: SessionFactory,
) -> None:
    async with sessions() as session:
        pack = await build_content_pack(
            session,
            connector="demo-agent",
            kinds=(
                ToolArtifactKind(),
                SkillArtifactKind(),
                PromptArtifactKind(),
                ResourceArtifactKind(),
            ),
        )
    entry = next(
        entry for entry in pack.archive.entries if entry.kind.value == "prompt"
    )
    captured = json.loads(
        pack.archive.data[entry.body.offset : entry.body.offset + entry.body.length]
    )
    assert captured["capture"] == {
        "method": "prompts/get",
        "bound_arguments": {},
        "kind": "rendered",
    }
    assert captured["result"]["messages"][0]["content"]["text"].startswith(
        "You operate the demo stream."
    )


async def test_prompt_capture_preserves_order_types_and_content_identity() -> None:
    result = mcp_types.GetPromptResult.model_validate(
        {
            "description": "rendered description",
            "_meta": {"origin": "fixture"},
            "messages": [
                {"role": "user", "content": {"type": "text", "text": "東京\nfirst"}},
                {
                    "role": "assistant",
                    "content": {
                        "type": "image",
                        "data": "AA==",
                        "mimeType": "image/png",
                    },
                },
                {
                    "role": "user",
                    "content": {
                        "type": "audio",
                        "data": "AA==",
                        "mimeType": "audio/wav",
                    },
                },
                {
                    "role": "assistant",
                    "content": {
                        "type": "resource",
                        "resource": {
                            "uri": "doc://notes",
                            "blob": "AA==",
                            "mimeType": "application/pdf",
                        },
                    },
                },
                {
                    "role": "user",
                    "content": {
                        "type": "resource_link",
                        "uri": "doc://manual",
                        "name": "manual",
                        "mimeType": "text/plain",
                    },
                },
            ],
        }
    )
    session = SimpleNamespace(
        server_identity=AsyncMock(return_value=SERVER),
        list_prompts=AsyncMock(
            return_value=[
                mcp_types.Prompt(name="demo", description="listed description")
            ]
        ),
        get_prompt=AsyncMock(return_value=result),
    )
    kind = PromptArtifactKind()
    pack = await build_content_pack(session, connector="demo-agent", kinds=(kind,))
    entry = pack.archive.entries[0]
    body = json.loads(
        pack.archive.data[entry.body.offset : entry.body.offset + entry.body.length]
    )
    assert body["description"] == "listed description"
    assert body["result"] == result.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    session.get_prompt.assert_awaited_once_with("demo", {})
    result.messages[0].content = mcp_types.TextContent(type="text", text="changed body")
    changed = await build_content_pack(session, connector="demo-agent", kinds=(kind,))
    assert changed.archive.data != pack.archive.data


async def test_prompt_capture_binds_required_arguments_as_template() -> None:
    prompt = mcp_types.Prompt(
        name="demo",
        description="listed description",
        arguments=[
            mcp_types.PromptArgument(name="topic", required=True),
            mcp_types.PromptArgument(name="tone", required=False),
        ],
    )
    result = mcp_types.GetPromptResult(
        messages=[
            mcp_types.PromptMessage(
                role="user",
                content=mcp_types.TextContent(type="text", text="about {{topic}}"),
            )
        ]
    )
    session = SimpleNamespace(
        server_identity=AsyncMock(return_value=SERVER),
        list_prompts=AsyncMock(return_value=[prompt]),
        get_prompt=AsyncMock(return_value=result),
    )
    kind = PromptArtifactKind()
    entries = await kind.list_entries(session, SERVER)
    session.get_prompt.assert_awaited_once_with("demo", {"topic": "{{topic}}"})
    entry = entries[0]
    kind.validate(entry)
    body = json.loads(entry.body)
    assert body["capture"] == {
        "method": "prompts/get",
        "bound_arguments": {"topic": "{{topic}}"},
        "kind": "template",
    }


async def test_prompt_capture_falls_back_to_template_when_server_rejects_bound_argument() -> (
    None
):
    """A typed required argument can refuse the `{{name}}` placeholder.

    FastMCP coerces each `prompts/get` argument to its declared type before
    rendering. A required `int`/`float`/`bool`/`list`/enum argument then
    refuses the string placeholder and the server answers with a protocol
    error, surfaced here as `McpPromptRejectedError`. The capture must still
    succeed, as a template built from the listed metadata alone.
    """
    prompt = mcp_types.Prompt(
        name="demo",
        description="listed description",
        arguments=[
            mcp_types.PromptArgument(name="count", required=True),
            mcp_types.PromptArgument(name="tone", required=False),
        ],
    )
    session = SimpleNamespace(
        server_identity=AsyncMock(return_value=SERVER),
        list_prompts=AsyncMock(return_value=[prompt]),
        get_prompt=AsyncMock(
            side_effect=McpPromptRejectedError("MCP prompts/get failed for 'demo'")
        ),
    )
    kind = PromptArtifactKind()
    entries = await kind.list_entries(session, SERVER)
    session.get_prompt.assert_awaited_once_with("demo", {"count": "{{count}}"})
    entry = entries[0]
    kind.validate(entry)
    body = json.loads(entry.body)
    assert body["capture"] == {
        "method": "prompts/get",
        "bound_arguments": {"count": "{{count}}"},
        "kind": "template",
    }
    assert body["result"]["messages"][0]["content"]["text"] == (
        "Prompt 'demo' takes arguments: count, tone."
    )


async def test_prompt_capture_still_fails_when_rejected_with_no_required_argument() -> (
    None
):
    """No placeholder was ever sent, so a rejection here is not a type refusal."""
    session = SimpleNamespace(
        list_prompts=AsyncMock(return_value=[mcp_types.Prompt(name="demo")]),
        get_prompt=AsyncMock(
            side_effect=McpPromptRejectedError("MCP prompts/get failed for 'demo'")
        ),
    )
    kind = PromptArtifactKind()
    with pytest.raises(McpPromptRejectedError):
        await kind.list_entries(session, SERVER)


async def test_prompt_capture_propagates_genuine_transport_failures() -> None:
    """A server-unreachable failure must still fail the capture, never fall back."""
    session = SimpleNamespace(
        list_prompts=AsyncMock(
            return_value=[
                mcp_types.Prompt(
                    name="demo",
                    arguments=[mcp_types.PromptArgument(name="count", required=True)],
                )
            ]
        ),
        get_prompt=AsyncMock(
            side_effect=McpTransportError("MCP prompts/get failed for 'demo'")
        ),
    )
    kind = PromptArtifactKind()
    with pytest.raises(McpTransportError):
        await kind.list_entries(session, SERVER)


@pytest.mark.parametrize(
    "failure",
    [
        "empty",
        "incomplete",
        "unknown_content",
        "wrong_role",
        "listing_only",
        "aggregate_bound",
    ],
)
async def test_prompt_capture_fails_closed(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = mcp_types.Prompt(name="demo")
    result = {
        "messages": [{"role": "user", "content": {"type": "text", "text": "body"}}]
    }
    if failure == "empty":
        result = {"messages": []}
    if failure == "incomplete":
        result["resultType"] = "input_required"
    if failure == "unknown_content":
        result["messages"][0]["content"] = {"type": "unknown", "text": "body"}
    if failure == "wrong_role":
        result["messages"][0]["role"] = "system"
    session = SimpleNamespace(
        list_prompts=AsyncMock(return_value=[prompt]),
        get_prompt=AsyncMock(return_value=result),
    )
    if failure == "aggregate_bound":
        single = await PromptArtifactKind().list_entries(session, SERVER)
        session.list_prompts.return_value = [
            prompt,
            prompt.model_copy(update={"name": "other"}),
        ]
        monkeypatch.setattr(
            "agent_connector_sdk.artifacts.prompts.DEFAULT_MAX_RESPONSE_BYTES",
            len(single[0].body),
        )
    kind = PromptArtifactKind()
    with pytest.raises(MalformedArtifactError):
        if failure == "listing_only":
            kind.validate(
                CapturedArtifact(
                    kind="prompt",
                    uri="prompt://demo-mcp/demo",
                    name="demo",
                    media_type="application/json",
                    body='{"name":"demo","arguments":[]}',
                    server=SERVER,
                )
            )
        else:
            await kind.list_entries(session, SERVER)


@pytest.mark.parametrize(
    "uri", ["prompt://other-server/demo", "prompt://demo-mcp/other-name"]
)
async def test_prompt_capture_rejects_uri_retagging(uri: str) -> None:
    session = SimpleNamespace(
        list_prompts=AsyncMock(return_value=[mcp_types.Prompt(name="demo")]),
        get_prompt=AsyncMock(
            return_value=mcp_types.GetPromptResult(
                messages=[
                    mcp_types.PromptMessage(
                        role="user",
                        content=mcp_types.TextContent(type="text", text="body"),
                    )
                ]
            )
        ),
    )
    kind = PromptArtifactKind()
    entry = (await kind.list_entries(session, SERVER))[0]
    kind.validate(entry)
    assert entry.uri == "prompt://demo-mcp/demo"
    retagged = entry.model_copy(update={"uri": uri})
    assert retagged.body == entry.body and retagged.server == entry.server
    assert retagged.name == entry.name
    with pytest.raises(MalformedArtifactError, match="prompt identity differs"):
        kind.validate(retagged)
