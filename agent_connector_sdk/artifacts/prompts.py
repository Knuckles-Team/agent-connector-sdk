"""Capture prompt definitions and complete rendered ``prompts/get`` results."""

from __future__ import annotations

import mcp_types

from agent_connector_sdk.artifacts.annotations import _annotations_from_mcp
from agent_connector_sdk.artifacts.common import (
    json_object,
    require_kind,
)
from agent_connector_sdk.artifacts.prompts_helpers import (
    _bound_arguments,
    _bounded_body,
    _capture_metadata,
    _definition,
    _prompt_uri,
    _result,
    _synthesized_result,
    _validate_contract,
    _validate_identity,
)
from agent_connector_sdk.contracts import CapturedArtifact, ServerIdentity
from agent_connector_sdk.http.bodies import DEFAULT_MAX_RESPONSE_BYTES
from agent_connector_sdk.ports.errors import MalformedArtifactError
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.transports.mcp_session import McpPromptRejectedError

__all__ = ["PromptArtifactKind"]


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


async def _render(
    session: McpSession, prompt: mcp_types.Prompt
) -> mcp_types.GetPromptResult:
    bound = _bound_arguments(prompt)
    try:
        return _result(await session.get_prompt(prompt.name, bound))
    except McpPromptRejectedError:
        if not bound:
            raise
        return _synthesized_result(prompt)


class PromptArtifactKind:
    """Captured prompts with listing metadata, ordered messages and content types.

    A prompt with no required argument is captured as a render. A prompt with
    a required argument is captured as a template: each required argument is
    bound to a `{{name}}` placeholder so the capture stays deterministic. A
    server that rejects a bound placeholder (for example a typed required
    argument) still captures as a template, from the listed metadata alone,
    instead of failing the whole capture.
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

        A server can refuse a bound placeholder outright, most often because
        a required argument is typed (int, float, bool, list, or enum) and
        the string placeholder fails its validation. That refusal surfaces as
        :class:`McpPromptRejectedError` and falls back to a synthesized
        template capture instead of failing the whole prompt listing. A
        prompt with no required argument never binds a placeholder, so the
        same refusal there is a genuine failure and still raises. Any other
        failure, such as the server being unreachable, always raises.
        """
        entries: list[CapturedArtifact] = []
        remaining = DEFAULT_MAX_RESPONSE_BYTES
        for listed in await session.list_prompts():
            prompt = _definition(listed)
            result = await _render(session, prompt)
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
