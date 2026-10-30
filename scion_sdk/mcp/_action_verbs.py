"""Verb classification and MCP hints for split action tools."""

from __future__ import annotations

import re
from typing import Any

_READ_ONLY = re.compile(
    r"(^|_)(list|get|read|show|status|describe|inspect|info|query|search|find|fetch|"
    r"check|validate|verify|scan|audit|analy[sz]e|calculate|compute|estimate|"
    r"preview|explain|view|count|history|stats?|metrics|export|diff|compare|"
    r"health|ping|test|detect|lookup|resolve|evaluate|discover|whoami|limits)(_|$)"
)
_DESTRUCTIVE = re.compile(
    r"(^|_)(delete|remove|destroy|drop|purge|wipe|erase|truncate|kill|terminate|"
    r"cancel|revoke|rotate|reset|uninstall|prune|halt|clear)(_|$)"
)
_MUTATING = re.compile(
    r"(^|_)(add|apply|assign|attach|authorize|cancel|change|clear|commit|create|"
    r"delete|deploy|destroy|detach|disable|drop|edit|enable|erase|execute|halt|"
    r"insert|install|invoke|kill|modify|move|patch|post|prune|purge|put|remove|"
    r"rename|reset|restart|revoke|rotate|run|send|set|start|stop|submit|terminate|"
    r"truncate|uninstall|update|upsert|wipe|write)(_|$)"
)


def _is_read_verb(action: str) -> bool:
    """Whether ``action`` has a read verb and no mutation verb."""
    return bool(_READ_ONLY.search(action)) and not _MUTATING.search(action)


def _annotations(action: str, declared: Any) -> dict[str, Any]:
    destructive = bool(_DESTRUCTIVE.search(action))
    read_only = _is_read_verb(action)
    open_world = getattr(declared, "openWorldHint", None)
    return {
        "title": action.replace("_", " ").title(),
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": read_only or destructive,
        "openWorldHint": True if open_world is None else open_world,
    }
