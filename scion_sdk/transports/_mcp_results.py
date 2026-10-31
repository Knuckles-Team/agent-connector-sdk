"""Decoding of MCP ``tools/call`` results."""

from __future__ import annotations

import json
from typing import Any


def decode_tool_result(result: Any) -> Any:
    """Decode a ``tools/call`` result: JSON text content first, then structured content."""
    texts = [
        block.text
        for block in getattr(result, "content", None) or []
        if isinstance(getattr(block, "text", None), str)
    ]
    joined = "\n".join(texts).strip()
    if not joined:
        return getattr(result, "structured_content", None)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined
