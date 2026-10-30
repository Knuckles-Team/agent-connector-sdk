"""Authority and backend contracts for bounded platform fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Protocol, get_args

from pydantic import BaseModel, ConfigDict, Field

from scion_sdk.adapters.platform_models import (
    BackendPolicy,
    Continuation,
    PlatformCapability,
    PlatformRecord,
    PlatformRequest,
    Provenance,
    Reason,
)
from scion_sdk.certify.fingerprints import output_schema_digest
from scion_sdk.identity import ActorContext


def platform_record_schema_digest(model: type[BaseModel]) -> str:
    """Return the SDK canonical output-schema digest for a record model."""
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise ValueError("platform output model is invalid")
    schema = model.model_json_schema()
    if (
        len(
            json.dumps(
                schema, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        )
        > 1_048_576
    ):
        raise ValueError("platform output schema exceeds the size limit")
    return "sha256:" + output_schema_digest({"outputSchema": schema})


class BackendPage(BaseModel):
    """A certified backend's bounded successful response."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    records: tuple[PlatformRecord, ...] = Field(max_length=100)
    continuation: Continuation | None = None
    provenance: Provenance | None = None


class BackendFailure(Exception):
    """A safe typed failure; upstream exception messages are not retained."""

    def __init__(
        self,
        reason: Reason,
        *,
        http_status: int | None = None,
        retry_after_ms: int | None = None,
    ) -> None:
        if (
            reason not in get_args(Reason)
            or (
                http_status is not None
                and (type(http_status) is not int or not 100 <= http_status <= 599)
            )
            or (
                retry_after_ms is not None
                and (
                    type(retry_after_ms) is not int or not 0 <= retry_after_ms <= 30_000
                )
            )
        ):
            raise ValueError("invalid backend failure")
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status
        self.retry_after_ms = retry_after_ms


class PlatformAuthorizer(Protocol):
    """Host authority for a verified actor, capability and connector policy."""

    async def authorize(
        self,
        actor: ActorContext,
        request: PlatformRequest,
        capability: PlatformCapability,
    ) -> bool: ...

    async def verify_continuation(
        self,
        actor: ActorContext,
        request: PlatformRequest,
        capability: PlatformCapability,
    ) -> bool: ...


class AdmittedPlatformBackend(Protocol):
    """One certified adapter; one call must perform exactly one network attempt."""

    @property
    def policy(self) -> BackendPolicy: ...

    @property
    def output_model(self) -> type[BaseModel]: ...

    async def read(
        self, request: PlatformRequest, *, timeout_ms: int
    ) -> BackendPage: ...


@dataclass(frozen=True)
class BackendAdmissionRefusal:
    """A backend excluded before any outbound attempt."""

    reason: Literal["unconfigured", "uncertified", "ineligible"]

    def __post_init__(self) -> None:
        if self.reason not in {"unconfigured", "uncertified", "ineligible"}:
            raise ValueError("invalid backend admission refusal")


class PlatformBackendAdmission(Protocol):
    """Resolve a backend only after exact identity and policy certification."""

    async def admit(
        self, actor: ActorContext, request: PlatformRequest, policy: BackendPolicy
    ) -> AdmittedPlatformBackend | BackendAdmissionRefusal: ...
