"""Fail-closed base model for data-preparation DTOs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProtocolModel(BaseModel):
    """Strict, frozen, extra-forbidding base for data-preparation records."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
