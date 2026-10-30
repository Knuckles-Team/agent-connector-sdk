"""Closed refusal vocabulary of the web-source contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RefusalReason = Literal[
    "robots_disallowed",
    "rate_limited",
    "size_exceeded",
    "unsupported_type",
    "egress_denied",
    "policy_refused",
    "extract_empty",
    "upstream_failed",
]
#: The closed refusal reasons, in contract order.
REFUSAL_REASONS: tuple[str, ...] = RefusalReason.__args__  # type: ignore[attr-defined]


class WebFetchRefusal(BaseModel):
    """A connector's refusal of one page, with a closed reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["refusal"] = "refusal"
    reason: RefusalReason
    detail: str = Field(default="", max_length=2000)


class WebSourceRefused(Exception):
    """Raised by a :class:`WebSource`; the tools return it as a refusal."""

    def __init__(self, reason: str, detail: str = "") -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError(f"unknown web-source refusal reason {reason!r}")
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)

    def refusal(self) -> WebFetchRefusal:
        return WebFetchRefusal(reason=self.reason, detail=self.detail[:2000])  # type: ignore[arg-type]
