"""Data classification labels carried by certification records."""

from __future__ import annotations

from enum import StrEnum


class DataClassification(StrEnum):
    """Regulatory classification label; the engine owns enforcement."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
