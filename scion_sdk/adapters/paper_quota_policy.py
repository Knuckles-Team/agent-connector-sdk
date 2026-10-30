"""Host-supplied paper provider quota policy."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PaperQuotaPolicy(BaseModel):
    """A globally named quota group and its admitted request spacing.

    Providers sharing one upstream limit must use the same credential group.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    provider_id: str = Field(min_length=1, max_length=256)
    credential_group: str = Field(min_length=1, max_length=256)
    policy_revision: str = Field(min_length=1, max_length=256)
    minimum_spacing_ns: int = Field(ge=1, le=3_600_000_000_000)

    @field_validator("provider_id", "credential_group", "policy_revision")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("quota identifiers must be nonblank and trimmed")
        return value
