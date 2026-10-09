"""Capture prompt definitions and complete rendered ``prompts/get`` results."""

from __future__ import annotations

import json
from typing import Any

import mcp_types
from pydantic import ValidationError

from agent_connector_sdk.artifacts.annotations import _annotations_from_mcp
from agent_connector_sdk.artifacts.common import (
    json_object,
    require_kind,
)
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.http.bodies import DEFAULT_MAX_RESPONSE_BYTES
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["PromptArtifactKind"]


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


def _prompt_entry(
    prompt: mcp_types.Prompt,
    server: ServerIdentity,
    result: mcp_types.GetPromptResult,
    *,
    remaining: int,
) -> CapturedArtifact:
    body = {
        "name": prompt.name,
        "description": prompt.description or "",
        "arguments": [
            argument.model_dump(mode="json", by_alias=True, exclude_none=True)
            for argument in prompt.arguments or []
        ],
        "definition": prompt.model_dump(mode="json", by_alias=True, exclude_none=True),
        "capture": _capture_metadata(prompt),
        "result": result.model_dump(mode="json", by_alias=True, exclude_none=True),
    }
    return CapturedArtifact(
        kind=PromptArtifactKind.kind,
        uri=_prompt_uri(server, prompt.name),
        name=prompt.name,
        media_type="application/json",
        body=_bounded_body(body, limit=remaining),
        server=server,
        annotations=_annotations_from_mcp(prompt),
    )


class PromptArtifactKind:
    """Captured prompts with listing metadata, ordered messages and content types.

    A prompt with no required argument is captured as a render. A prompt with
    a required argument is captured as a template: each required argument is
    bound to a `{{name}}` placeholder so the capture stays deterministic.
    """

    kind = "prompt"

    async def list_entries(
        self, session: McpSession, server: ServerIdentity
    ) -> tuple[CapturedArtifact, ...]:
        """Get each prompt with no invented values; bound the aggregate capture.

        A required argument has no real value at capture time, so it is bound
        to a `{{name}}` placeholder and the capture is recorded as a template.
        Optional arguments stay unbound. A prompt with no required arguments
        is still captured as a render, exactly as before.
        """
        entries: list[CapturedArtifact] = []
        remaining = DEFAULT_MAX_RESPONSE_BYTES
        for listed in await session.list_prompts():
            prompt = _definition(listed)
            bound = _bound_arguments(prompt)
            result = _result(await session.get_prompt(prompt.name, bound))
            entry = _prompt_entry(prompt, server, result, remaining=remaining)
            self.validate(entry)
            remaining -= len(entry.body)
            entries.append(entry)
        return tuple(entries)

    def validate(self, entry: CapturedArtifact) -> None:
        """Require a complete typed render bound to its listed definition."""
        require_kind(entry, self.kind)
        if len(entry.body.encode("utf-8")) > DEFAULT_MAX_RESPONSE_BYTES:
            raise MalformedArtifactError(
                "MCP prompt capture exceeds the response byte bound"
            )
        document = json_object(entry)
        prompt = _definition(document.get("definition"))
        _validate_identity(entry, prompt)
        _validate_contract(document, prompt, entry)
        _result(document.get("result"))
