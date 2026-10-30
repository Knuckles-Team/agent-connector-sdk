"""Separate prompt classification from the persona metadata served over MCP."""

from typing import Any


class ContentError(ValueError):
    """A connector content file is malformed or missing."""


def _prompt_pack_metadata(
    document: dict[str, Any], metadata: dict[str, Any]
) -> dict[str, Any]:
    """Carry the prompt role and target alongside existing MCP persona metadata."""
    role = document.get("role", "task")
    if role not in ("system", "task", "template"):
        raise ContentError("prompt role must be system, task or template")
    target = (
        document.get("systemPromptFor")
        or document.get("serves")
        or document.get("ontology_class")
    )
    return {**metadata, "team.knuckles/prompt-pack": {"role": role, "serves": target}}
