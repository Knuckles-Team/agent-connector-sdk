"""Fail-closed destructive confirmation across supported MCP protocol eras."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any

from mcp.types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult
from pydantic import BaseModel, StrictBool

_logger = logging.getLogger(__name__)

_MODERN_MCP_PROTOCOL = "2026-07-28"
_CONFIRMATION_INPUT_KEY = "destructive_action_confirmation"


class _DestructiveActionConfirmation(BaseModel):
    confirmed: StrictBool


class _FailClosedInputRequiredResult(InputRequiredResult):
    """Keep legacy boolean guards fail-closed while new callers propagate us."""

    def __bool__(self) -> bool:
        return False


def _confirmation_binding(
    action_description: str, arguments: Mapping[str, Any] | None
) -> str | None:
    """Bind a modern confirmation response to this action and its arguments."""
    try:
        payload = json.dumps(
            {"action": action_description, "arguments": dict(arguments or {})},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _input_required_result(
    action_description: str, binding: str
) -> InputRequiredResult:
    """Ask for an explicit boolean confirmation in a modern MCP round trip."""
    return _FailClosedInputRequiredResult(
        result_type="input_required",
        input_requests={
            _CONFIRMATION_INPUT_KEY: ElicitRequest(
                method="elicitation/create",
                params=ElicitRequestFormParams(
                    message=f"Are you sure you want to {action_description}?",
                    requested_schema={
                        "type": "object",
                        "properties": {
                            "confirmed": {
                                "type": "boolean",
                                "title": "Confirm this destructive action",
                            }
                        },
                        "required": ["confirmed"],
                    },
                ),
            )
        },
        request_state=binding,
    )


def _accepted_modern_response(response: Any) -> bool:
    content = getattr(response, "content", None)
    return bool(
        getattr(response, "action", None) == "accept"
        and isinstance(content, Mapping)
        and content.get("confirmed") is True
    )


def _confirm_modern_destructive(
    ctx: Any,
    action_description: str,
    arguments: Mapping[str, Any] | None,
) -> bool | InputRequiredResult:
    binding = _confirmation_binding(action_description, arguments)
    if binding is None:
        _logger.warning("Could not bind destructive confirmation; operation denied")
        return False

    responses = getattr(ctx, "input_responses", None)
    request_state = getattr(ctx, "request_state", None)
    if responses is None and request_state is None:
        return _input_required_result(action_description, binding)
    if request_state != binding or not isinstance(responses, Mapping):
        return False
    return _accepted_modern_response(responses.get(_CONFIRMATION_INPUT_KEY))


async def _confirm_legacy_destructive(ctx: Any, action_description: str) -> bool:
    try:
        result = await ctx.elicit(
            f"Are you sure you want to {action_description}?",
            response_type=_DestructiveActionConfirmation,
        )
    except Exception:
        _logger.warning("Elicitation failed; destructive operation denied")
        return False
    return bool(
        result.action == "accept" and getattr(result.data, "confirmed", None) is True
    )


async def ctx_confirm_destructive(
    ctx: Any,
    action_description: str,
    *,
    confirmation_arguments: Mapping[str, Any] | None = None,
) -> bool | InputRequiredResult:
    """Require explicit confirmation in the live negotiated MCP era.

    Modern MCP returns an input request and only continues when the client
    retries with an accepted response bound to the same action and arguments.
    Earlier protocol versions use FastMCP's elicitation request. Any missing
    context, response, or protocol identity denies by default.
    """
    if not ctx:
        return False
    request_context = getattr(ctx, "request_context", None)
    protocol_version = getattr(request_context, "protocol_version", None)
    if not isinstance(protocol_version, str):
        return False
    if protocol_version >= _MODERN_MCP_PROTOCOL:
        return _confirm_modern_destructive(
            ctx, action_description, confirmation_arguments
        )
    return await _confirm_legacy_destructive(ctx, action_description)
