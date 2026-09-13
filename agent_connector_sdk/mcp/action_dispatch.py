"""Action routing for condensed ``<service>_<domain>`` MCP tools.

Extracted from ``agent_utilities.mcp.action_dispatch``. Many fleet tools take a
free-form ``action`` string dispatched to a client method. These helpers give
every such tool the same three behaviours:

1. **Discovery**: an action in :data:`DISCOVERY_ACTIONS` returns the valid names.
2. **Aliasing**: explicit aliases and intuitive plurals resolve to a real name.
3. **Did-you-mean**: an unknown action raises with close matches.

:func:`dispatch` / :func:`dispatch_async` serve getattr-dynamic servers;
:func:`resolve_action` serves servers with an explicit ``if``/``elif`` chain.
"""

from __future__ import annotations

import difflib
import inspect
import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from agent_connector_sdk.mcp.concurrency import (
    fold_body_arguments,
    invoke_client_method,
)
from agent_connector_sdk.mcp.context import ctx_confirm_destructive

__all__ = [
    "DISCOVERY_ACTIONS",
    "canonicalize",
    "dispatch",
    "dispatch_async",
    "is_destructive_action",
    "parse_json_object",
    "public_actions",
    "resolve_action",
    "suggest",
    "unknown_action_error",
]

#: Action strings that request the list of valid actions instead of executing one.
DISCOVERY_ACTIONS = ("list_actions", "help", "actions")

_MAX_JSON_OBJECT_INPUT = 64 * 1024

_DESTRUCTIVE_ACTION_TOKENS = frozenset(
    {"deactivate", "delete", "destroy", "drop", "purge", "remove"}
)


def public_actions(client: Any) -> list[str]:
    """Sorted public, callable attribute names of a client object or class."""
    return sorted(
        name
        for name in dir(client)
        if not name.startswith("_") and callable(getattr(client, name, None))
    )


def parse_json_object(
    value: str | bytes | bytearray | None, parameter: str = "params_json"
) -> dict[str, Any]:
    """Parse one bounded JSON object without echoing caller input on failure.

    Raises:
        ValueError: when the input is too large, not JSON, or not an object.
    """
    if value is None:
        return {}
    if not isinstance(value, str | bytes | bytearray):
        raise ValueError(f"{parameter} must be valid JSON")
    if not value.strip():
        return {}
    if len(value) > _MAX_JSON_OBJECT_INPUT:
        raise ValueError(
            f"{parameter} exceeds the {_MAX_JSON_OBJECT_INPUT}-unit input limit"
        )
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError(f"{parameter} must be valid JSON") from None
    if not isinstance(parsed, dict):
        raise ValueError(f"{parameter} must decode to a JSON object")
    return parsed


def is_destructive_action(
    action: str, operation: Mapping[str, Any] | None = None
) -> bool:
    """Classify an action by explicit metadata first, then by exact name tokens."""
    if operation:
        if operation.get("destructive") is not None:
            return bool(operation["destructive"])
        if str(operation.get("http", "")).upper() == "DELETE":
            return True
    return bool(_DESTRUCTIVE_ACTION_TOKENS.intersection(action.casefold().split("_")))


def suggest(action: str, valid: Iterable[str], *, n: int = 3) -> list[str]:
    """Close matches for ``action`` among ``valid``."""
    return difflib.get_close_matches(action, list(valid), n=n)


def _plural_candidates(action: str) -> list[str]:
    if not action.endswith("s"):
        return []
    candidates = [action[:-1]]
    if action.endswith("es"):
        candidates.append(action[:-2])
    return candidates


def canonicalize(
    action: str, valid: Iterable[str], *, aliases: Mapping[str, str] | None = None
) -> str | None:
    """Resolve ``action`` to a member of ``valid``, or ``None``.

    Tries the action itself, then an explicit alias, then plural-to-singular.
    """
    valid_set = set(valid)
    if action in valid_set:
        return action
    if aliases and aliases.get(action) in valid_set:
        return aliases[action]
    for candidate in _plural_candidates(action):
        if candidate in valid_set:
            return candidate
    return None


def unknown_action_error(
    action: str, valid: Iterable[str], *, target: str = ""
) -> ValueError:
    """Build a ValueError with did-you-mean hints and a discovery pointer."""
    names = list(valid)
    matches = suggest(action, names)
    hint = f" Did you mean: {', '.join(matches)}?" if matches else ""
    where = f" on {target}" if target else ""
    return ValueError(
        f"Unknown action '{action}'{where}.{hint} "
        f"Call with action='list_actions' to see all {len(names)} available actions."
    )


def resolve_action(
    action: str,
    valid_actions: Iterable[str],
    *,
    aliases: Mapping[str, str] | None = None,
    service: str = "",
) -> str | dict[str, Any]:
    """Resolve an action for an explicit ``if``/``elif`` dispatcher.

    Returns:
        A ``{"service", "actions"}`` discovery payload for a discovery keyword,
        otherwise the canonical action name.

    Raises:
        ValueError: for an unknown action.
    """
    names = list(valid_actions)
    if action in DISCOVERY_ACTIONS:
        return {"service": service, "actions": sorted(names)}
    canonical = canonicalize(action, names, aliases=aliases)
    if canonical is None:
        raise unknown_action_error(action, names, target=service or "this tool")
    return canonical


def dispatch(
    client: Any,
    action: str,
    kwargs: Mapping[str, Any] | None = None,
    *,
    aliases: Mapping[str, str] | None = None,
    service: str = "",
    result_coercer: Callable[[Any], Any] | None = None,
) -> Any:
    """Resolve and synchronously execute ``action`` on a getattr-dynamic client."""
    actions = public_actions(client)
    target = service or type(client).__name__
    if action in DISCOVERY_ACTIONS:
        return {"service": target, "actions": actions}
    canonical = canonicalize(action, actions, aliases=aliases)
    if canonical is None:
        raise unknown_action_error(action, actions, target=target)
    method = getattr(client, canonical)
    result = method(**fold_body_arguments(method, (), dict(kwargs or {})))
    return result_coercer(result) if result_coercer is not None else result


async def dispatch_async(
    client: Any,
    action: str,
    kwargs: Mapping[str, Any] | None = None,
    *,
    aliases: Mapping[str, str] | None = None,
    service: str = "",
    result_coercer: Callable[[Any], Any] | None = None,
    ctx: Any = None,
    operation: Mapping[str, Any] | None = None,
) -> Any:
    """Resolve and execute ``action`` without blocking the MCP event loop.

    A destructive action requires an affirmative live-context elicitation; a
    missing context or failed elicitation returns a cancellation payload.
    """
    actions = public_actions(client)
    target = service or type(client).__name__
    if action in DISCOVERY_ACTIONS:
        return {"service": target, "actions": actions}
    canonical = canonicalize(action, actions, aliases=aliases)
    if canonical is None:
        raise unknown_action_error(action, actions, target=target)
    if is_destructive_action(
        canonical, operation
    ) and not await ctx_confirm_destructive(ctx, canonical):
        return {"cancelled": True, "operation": canonical}
    result = await invoke_client_method(
        getattr(client, canonical), **dict(kwargs or {})
    )
    if result_coercer is None:
        return result
    coerced = result_coercer(result)
    return await coerced if inspect.isawaitable(coerced) else coerced
