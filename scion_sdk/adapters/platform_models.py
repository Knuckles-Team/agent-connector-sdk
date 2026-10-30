"""Closed data contracts for declared platform read/search capabilities.

These contracts describe policy and results only; they do not authorize a
caller, certify equivalence, make network calls, or implement fallback.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scion_sdk.credentials.references import parse_secret_reference

Text = Annotated[str, Field(min_length=1, max_length=256)]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Operation = Literal["read", "search"]
Reason = Literal[
    "invalid_request",
    "unsupported_capability",
    "unauthorized",
    "no_backend",
    "chain_exhausted",
    "deadline_exceeded",
    "cancelled",
    "rate_limited",
    "egress_denied",
    "trust_failed",
    "invalid_response",
    "not_found",
    "connection_failed",
    "timeout",
    "upstream_unavailable",
]


class _ClosedModel(BaseModel):
    """Strict closed contract; receiving code must still authenticate inputs."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, hide_input_in_errors=True
    )


class EquivalenceContract(_ClosedModel):
    platform_id: Text
    resource_visibility: Literal["public", "private"]
    account_scope: Text
    query_semantics: Text
    output_schema_digest: Digest


class BackendPolicy(_ClosedModel):
    backend_id: Text
    adapter_id: Text
    adapter_version: Text
    enabled: bool
    auth_mode: Literal["public", "credential"]
    credential_ref: Text | None = Field(repr=False)
    allowed_destinations: tuple[Text, ...] = Field(min_length=1, max_length=16)
    equivalence_contract: EquivalenceContract
    quota_group: Text
    max_attempts: int = Field(default=2, ge=1, le=2)
    timeout_ms: int = Field(default=10_000, ge=1, le=10_000)
    retry_policy: Text
    output_schema_digest: Digest

    @model_validator(mode="after")
    def validate_policy(self) -> BackendPolicy:
        if (self.auth_mode == "public") != (self.credential_ref is None):
            raise ValueError("credential reference must match auth mode")
        if self.credential_ref is not None:
            parse_secret_reference(self.credential_ref)
        if self.output_schema_digest != self.equivalence_contract.output_schema_digest:
            raise ValueError("backend output schema differs from equivalence contract")
        if (
            self.equivalence_contract.resource_visibility == "private"
            and self.auth_mode == "public"
        ):
            raise ValueError("public access cannot cover private resources")
        return self


class PlatformCapability(_ClosedModel):
    platform_id: Text
    channel_id: Text
    operation: Operation
    schema_revision: Text
    policy_revision: Text
    required_scope: Text
    backends: tuple[BackendPolicy, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_backends(self) -> PlatformCapability:
        if len({b.backend_id for b in self.backends}) != len(self.backends):
            raise ValueError("duplicate backends")
        equivalence = self.backends[0].equivalence_contract
        if equivalence.platform_id != self.platform_id or any(
            b.equivalence_contract != equivalence for b in self.backends
        ):
            raise ValueError("backends must share the declared equivalence contract")
        return self


class Continuation(_ClosedModel):
    token: Text = Field(repr=False)
    tenant_id: Text
    query_digest: Digest
    backend_id: Text
    policy_revision: Text
    output_schema_digest: Digest


class PlatformRequest(_ClosedModel):
    request_id: Text
    tenant_id: Text
    principal_id: Text
    connector_id: Text
    platform_id: Text
    channel_id: Text
    operation: Operation
    target: Text | None = Field(default=None, repr=False)
    query: Text | None = Field(default=None, repr=False)
    continuation: Continuation | None = Field(default=None, repr=False)
    limit: int = Field(default=100, ge=1, le=100)
    deadline_ms: int = Field(default=30_000, ge=1, le=30_000)

    @model_validator(mode="after")
    def validate_request(self) -> PlatformRequest:
        if self.operation == "read" and (self.target is None or self.query is not None):
            raise ValueError("read requires only a target")
        if self.operation == "search" and (
            self.query is None or self.target is not None
        ):
            raise ValueError("search requires only a query")
        if (
            self.continuation is not None
            and self.continuation.tenant_id != self.tenant_id
        ):
            raise ValueError("continuation tenant differs from request")
        return self


class BackendAttempt(_ClosedModel):
    sequence: int = Field(ge=1, le=8)
    backend_id: Text
    attempt_number: int = Field(ge=1, le=2)
    outcome: Literal["ok", "failed", "cancelled"]
    reason: Reason | None = None
    started_at: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0, le=30_000)
    retry_after_ms: int | None = Field(default=None, ge=0, le=30_000)
    response_digest: Digest | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)

    @model_validator(mode="after")
    def outcome_has_reason(self) -> BackendAttempt:
        if (self.outcome == "ok") != (self.reason is None):
            raise ValueError("only successful attempts omit a reason")
        return self


class SkippedBackend(_ClosedModel):
    backend_id: Text
    reason: Literal["disabled", "unconfigured", "uncertified", "ineligible"]


class BackendState(_ClosedModel):
    backend_id: Text
    health: Literal["untested", "disabled", "unconfigured", "healthy", "failed"]
    reason: Reason | None = None
    observed_at: int | None = Field(default=None, ge=0)


class ChannelStatus(_ClosedModel):
    tenant_id: Text
    connector_id: Text
    account_scope: Text
    platform_id: Text
    channel_id: Text
    operation: Operation
    policy_revision: Text
    selected_backend: Text | None
    health: Literal["unknown", "healthy", "degraded", "unavailable"]
    backend_states: tuple[BackendState, ...] = Field(max_length=4)
    observed_at: int = Field(ge=0)
    expires_at: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_times(self) -> ChannelStatus:
        if self.expires_at < self.observed_at:
            raise ValueError("status expires before observation")
        return self


class Provenance(_ClosedModel):
    source_id: Text
    backend_id: Text
    retrieved_at: int = Field(ge=0)
    content_digest: Digest
    coverage: Text


class PlatformRecord(_ClosedModel):
    content: dict[str, JsonValue] = Field(repr=False)
    provenance: Provenance


class PlatformResult(_ClosedModel):
    request_id: Text
    request_digest: Digest
    tenant_id: Text | None = None
    principal_id: Text | None = None
    connector_id: Text | None = None
    platform_id: Text | None = None
    channel_id: Text | None = None
    operation: Operation | None = None
    policy_revision: Text | None = None
    output_schema_digest: Digest | None = None
    outcome: Literal["ok", "refused"]
    reason: Reason | None = None
    records: tuple[PlatformRecord, ...] = Field(default=(), max_length=100)
    continuation: Continuation | None = None
    selected_backend: Text | None = None
    attempts: tuple[BackendAttempt, ...] = Field(default=(), max_length=8)
    skipped_backends: tuple[SkippedBackend, ...] = Field(default=(), max_length=4)
    channel_status: ChannelStatus | None = None
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> PlatformResult:
        request_scope = (
            self.tenant_id,
            self.principal_id,
            self.connector_id,
            self.platform_id,
            self.channel_id,
            self.operation,
        )
        if any(value is not None for value in request_scope) and not all(
            value is not None for value in request_scope
        ):
            raise ValueError("result request scope must be complete")
        if (self.policy_revision is None) != (self.output_schema_digest is None):
            raise ValueError("result policy and schema must be bound together")
        if self.channel_status is not None and self.tenant_id is not None:
            status = self.channel_status
            if (
                status.tenant_id,
                status.connector_id,
                status.platform_id,
                status.channel_id,
                status.operation,
                status.policy_revision,
            ) != (
                self.tenant_id,
                self.connector_id,
                self.platform_id,
                self.channel_id,
                self.operation,
                self.policy_revision,
            ):
                raise ValueError("result status does not match its request scope")
        if self.outcome == "refused":
            if (
                self.reason is None
                or self.records
                or self.continuation is not None
                or self.selected_backend is not None
            ):
                raise ValueError("refusal requires reason and no success data")
        elif self.reason is not None or self.selected_backend is None:
            raise ValueError("success requires backend and no refusal reason")
        if (
            sum(
                len(
                    json.dumps(
                        record.content,
                        allow_nan=False,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                for record in self.records
            )
            > 1_048_576
        ):
            raise ValueError("result exceeds byte limit")
        if tuple(a.sequence for a in self.attempts) != tuple(
            range(1, len(self.attempts) + 1)
        ):
            raise ValueError("attempt sequence must be complete and ordered")
        if self.outcome == "ok" and (
            not self.attempts
            or self.attempts[-1].outcome != "ok"
            or self.attempts[-1].backend_id != self.selected_backend
            or any(attempt.outcome != "failed" for attempt in self.attempts[:-1])
            or any(
                record.provenance.backend_id != self.selected_backend
                for record in self.records
            )
            or (
                self.continuation is not None
                and self.continuation.backend_id != self.selected_backend
            )
            or (
                self.provenance is not None
                and self.provenance.backend_id != self.selected_backend
            )
        ):
            raise ValueError("success evidence must match the selected backend")
        if self.outcome == "refused" and any(
            attempt.outcome == "ok" for attempt in self.attempts
        ):
            raise ValueError("refusal cannot contain a successful attempt")
        return self


def validate_request_binding(
    request: PlatformRequest, capability: PlatformCapability
) -> None:
    """Check a continuation against this request and policy before dispatch.

    This structural check is not authentication or proof of equivalence.
    """
    request = PlatformRequest.model_validate(request.model_dump(mode="python"))
    capability = PlatformCapability.model_validate(capability.model_dump(mode="python"))
    if (request.platform_id, request.channel_id, request.operation) != (
        capability.platform_id,
        capability.channel_id,
        capability.operation,
    ):
        raise ValueError("request does not match capability")
    continuation = request.continuation
    if continuation is None:
        return
    query = request.query if request.operation == "search" else request.target
    if query is None:
        raise ValueError("request has no query or target")
    digest = "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()
    backend = next(
        (
            item
            for item in capability.backends
            if item.backend_id == continuation.backend_id
        ),
        None,
    )
    if (
        continuation.query_digest != digest
        or continuation.policy_revision != capability.policy_revision
        or backend is None
        or continuation.output_schema_digest != backend.output_schema_digest
    ):
        raise ValueError("continuation does not match request and capability")
