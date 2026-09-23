"""What one SDK-owned ``Decide`` call concluded, and why."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Choice:
    """What a decision point concluded, and why.

    ``decided`` is true only when EG executed an option a call site offered;
    otherwise ``option_id`` is the deterministic fallback's answer and
    ``reason`` names why EG did not decide (``no_runner``, ``unbound``,
    ``unavailable: ...``, ``abstained: ...``, ``advisory``,
    ``foreign_option: ...``). ``advisory`` carries EG's uncalibrated scores
    when it gave any: they are shown, never obeyed. A call site never needs
    to re-derive the fallback -- ``option_id`` is always a concrete answer.
    """

    option_id: str
    decided: bool
    reason: str
    advisory: Mapping[str, int] = field(default_factory=dict)


__all__ = ["Choice"]
