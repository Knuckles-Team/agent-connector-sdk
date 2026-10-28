"""Component health and enabled-only alert decisions.

These values classify supplied observations. They do not probe a component,
authenticate configuration, or deliver an alert.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["ComponentHealthState", "should_alert"]


class ComponentHealthState(BaseModel):
    """A typed observation of a component's configuration and health."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    component_id: str = Field(min_length=1, max_length=512, pattern=r"^\S(?:.*\S)?$")
    state: Literal["healthy", "degraded", "unavailable", "not_configured"]
    configuration_status: Literal["disabled", "not_initialized", "initialized"]
    enabled: bool
    last_check_time: datetime
    availability_reason: str | None = Field(default=None, min_length=1, max_length=512)
    alert_suppression_reason: str | None = Field(
        default=None, min_length=1, max_length=512
    )

    @model_validator(mode="after")
    def _coherent_state(self) -> ComponentHealthState:
        if self.last_check_time.utcoffset() is None:
            raise ValueError("health timestamp must include a timezone")
        if self.configuration_status == "initialized":
            if not self.enabled or self.state == "not_configured":
                raise ValueError(
                    "initialized health requires an enabled configured component"
                )
        elif self.state != "not_configured":
            raise ValueError(
                "uninitialized or disabled component cannot report a live state"
            )
        if self.configuration_status == "disabled" and (
            self.enabled or self.alert_suppression_reason is None
        ):
            raise ValueError("disabled component requires a suppression reason")
        return self


def should_alert(observation: ComponentHealthState) -> bool:
    """Alert only on a degraded or unavailable enabled, initialized component."""
    return (
        observation.enabled
        and observation.configuration_status == "initialized"
        and observation.state in {"degraded", "unavailable"}
    )
