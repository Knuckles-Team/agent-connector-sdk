"""Backend-agnostic node shape the write-back sinks read."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """A graph node handed to a sink: ``type`` is the label, ``props`` the scalars."""

    id: str
    type: str
    props: dict[str, Any] = Field(default_factory=dict)
