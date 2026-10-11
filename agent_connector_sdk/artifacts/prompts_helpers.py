"""Pure validation and rendering helpers for :mod:`agent_connector_sdk.artifacts.prompts`."""

from __future__ import annotations

import json
from typing import Any

import mcp_types
from pydantic import ValidationError

from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.ports.errors import MalformedArtifactError


def _definition(value: Any) -> mcp_types.Prompt:
    try:
        prompt = mcp_types.Prompt.model_validate(value)
    except ValidationError as exc:
        raise MalformedArtifactError("MCP prompt definition is malformed") from exc
    arguments = prompt.arguments or []
    names = [argument.name for argument in arguments]
    if not prompt.name.strip() or any(not name.strip() for name in names):
        raise MalformedArtifactError("MCP prompt requires nonempty names")
    if len(names) != len(set(names)):
        raise MalformedArtifactError(
            f"prompt {prompt.name!r} declares a duplicate argument name"
        )
    return prompt


def _bound_arguments(prompt: mcp_types.Prompt) -> dict[str, str]:
    """Placeholder text bound to each required argument, deterministic and stable.

    A required argument has no real value at capture time. Binding it to a
    `{{name}}` placeholder lets the server render a template instead of
    refusing the prompt. Optional arguments stay unbound.
    """
    return {
        argument.name: f"{{{{{argument.name}}}}}"
        for argument in prompt.arguments or []
        if argument.required
    }


def _synthesized_result(prompt: mcp_types.Prompt) -> mcp_types.GetPromptResult:
    """A deterministic placeholder render for a prompt the server rejected.

    A typed required argument (int, float, bool, list, or enum) can refuse
    the `{{name}}` placeholder `prompts/get` sends for it. The capture then
    lists the prompt's own arguments instead of a live render, computed only
    from the listed definition, so it stays deterministic and never depends
    on the server accepting a placeholder value.
    """
    names = [argument.name for argument in prompt.arguments or []]
    text = (
        f"Prompt {prompt.name!r} takes arguments: {', '.join(names)}."
        if names
        else f"Prompt {prompt.name!r} takes no arguments."
    )
    return mcp_types.GetPromptResult(
        messages=[
            mcp_types.PromptMessage(
                role="user", content=mcp_types.TextContent(type="text", text=text)
            )
        ]
    )


def _result(value: Any) -> mcp_types.GetPromptResult:
    try:
        result = mcp_types.GetPromptResult.model_validate(value)
    except ValidationError as exc:
        raise MalformedArtifactError("MCP prompt result is malformed") from exc
    if result.result_type != "complete" or not result.messages:
        raise MalformedArtifactError("MCP prompt capture requires complete messages")
    return result


def _bounded_body(document: dict[str, Any], *, limit: int) -> str:
    chunks: list[str] = []
    size = 0
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    for chunk in encoder.iterencode(document):
        size += len(chunk)
        if size > limit:
            raise MalformedArtifactError(
                "MCP prompt capture exceeds the response byte bound"
            )
        chunks.append(chunk)
    return "".join(chunks)


def _prompt_uri(server: ServerIdentity, name: str) -> str:
    return f"prompt://{server.name}/{name}"


def _validate_identity(entry: CapturedArtifact, prompt: mcp_types.Prompt) -> None:
    if entry.name != prompt.name or entry.uri != _prompt_uri(entry.server, prompt.name):
        raise MalformedArtifactError(
            "MCP prompt identity differs from its server and definition"
        )


def _capture_metadata(prompt: mcp_types.Prompt) -> dict[str, Any]:
    bound = _bound_arguments(prompt)
    return {
        "method": "prompts/get",
        "bound_arguments": bound,
        "kind": "template" if bound else "rendered",
    }


def _validate_contract(
    document: dict[str, Any], prompt: mcp_types.Prompt, entry: CapturedArtifact
) -> None:
    expected = _capture_metadata(prompt)
    if document.get("capture") != expected or document.get("name") != entry.name:
        raise MalformedArtifactError(f"{entry.uri} has a malformed prompt capture")
    if document.get("description") != (prompt.description or ""):
        raise MalformedArtifactError(f"{entry.uri} has a malformed prompt contract")
    arguments = [
        argument.model_dump(mode="json", by_alias=True, exclude_none=True)
        for argument in prompt.arguments or []
    ]
    if document.get("arguments") != arguments:
        raise MalformedArtifactError(
            f"{entry.uri} argument contract differs from its definition"
        )
