"""Prompt documents served as native MCP prompts by :mod:`scion_sdk.mcp.content`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp.prompts import Prompt

from scion_sdk.mcp.prompt_pack_meta import ContentError, _prompt_pack_metadata

#: Reverse-DNS ``_meta`` key carrying a prompt's role, topic, version and target.
PROMPT_META_KEY = "team.knuckles/prompt"


def _prompt_document(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContentError(f"prompt {path.name} is not readable JSON") from exc
    if not isinstance(document, dict):
        raise ContentError(f"prompt {path.name} has no instructions.core_directive")
    return document


def _composed_text(path: Path, document: dict[str, Any]) -> str:
    instructions = document.get("instructions")
    directive = (
        instructions.get("core_directive") if isinstance(instructions, dict) else None
    )
    if not isinstance(directive, str) or not directive.strip():
        raise ContentError(f"prompt {path.name} has no instructions.core_directive")
    return directive


def _prompt_directive(path: Path) -> tuple[str, str]:
    document = _prompt_document(path)
    return _composed_text(path, document), str(document.get("description") or "")


#: ``metadata`` keys already carried under their own meta name.
_META_FOLDED = frozenset({"topic", "tone", "style", "useCase", "use_case"})


def _text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _meta_values(document: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    raw_identity = document.get("identity")
    identity: dict[str, Any] = raw_identity if isinstance(raw_identity, dict) else {}
    return {
        "role": identity.get("role") or document.get("role"),
        "goal": identity.get("goal") or document.get("goal"),
        "topic": metadata.get("topic") or document.get("topic"),
        "tone": metadata.get("tone") or document.get("tone"),
        "style": metadata.get("style") or document.get("style"),
        "version": document.get("prompt_version"),
        "systemPromptFor": document.get("systemPromptFor")
        or document.get("serves")
        or document.get("ontology_class"),
        "useCase": _text(
            document.get("useCase"), metadata.get("useCase"), document.get("use_case")
        ),
    }


def _prompt_meta(document: dict[str, Any]) -> dict[str, Any]:
    """Role, goal, topic, tone, style, version, use case and system-prompt target.

    These become the ``team.knuckles/prompt`` entry of ``prompts/list`` ``_meta``.
    """
    raw_metadata = document.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    values = _meta_values(document, metadata)
    declared = {
        key: value
        for key, value in metadata.items()
        if key not in _META_FOLDED and isinstance(value, (str, int, float, bool))
    }
    return {PROMPT_META_KEY: {**declared, **{k: v for k, v in values.items() if v}}}


def _prompt_title(document: dict[str, Any]) -> str | None:
    identity = document.get("identity")
    return _text(
        document.get("title"),
        identity.get("role") if isinstance(identity, dict) else None,
    )


def _prompt_tags(document: dict[str, Any]) -> set[str]:
    """The prompt's declared ``tags`` plus ``prompt`` and, for a system prompt, ``system``."""
    declared = document.get("tags")
    tags = (
        {t.strip() for t in declared if isinstance(t, str) and t.strip()}
        if isinstance(declared, list)
        else set()
    )
    tags.add("prompt")
    if _prompt_meta(document)[PROMPT_META_KEY].get("systemPromptFor"):
        tags.add("system")
    return tags


def _register_prompt(mcp: Any, path: Path) -> None:
    document = _prompt_document(path)
    text = _composed_text(path, document)

    def render() -> str:
        return text

    mcp.add_prompt(
        Prompt.from_function(
            render,
            name=path.stem,
            title=_prompt_title(document),
            description=str(document.get("description") or ""),
            tags=_prompt_tags(document),
            meta=_prompt_pack_metadata(document, _prompt_meta(document)),
        )
    )
