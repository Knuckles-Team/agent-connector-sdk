"""Strict, privacy-safe contracts for optional operator data-quality runs.

This package is deliberately separate from the Arrow preparation kernel.  A
certification run can describe a human-facing Data Docs artifact, but it never
accepts or returns the report body, a provider query, credentials, or source
rows.  The native engine's SHACL/ICV decision remains authoritative; this
contract is an optional operator observation only.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from scion_sdk.data_prep._base import ProtocolModel
from scion_sdk.data_prep._classification import DataClassification

type CertificationBackend = Literal["great_expectations", "pandera"]
type CertificationState = Literal[
    "not_requested", "unavailable", "denied", "failed", "passed"
]
type FailureCode = Literal[
    "arrow_dependency_unavailable",
    "provider_dependency_unavailable",
    "authorization_expired",
    "invalid_sample",
    "sample_limit_exceeded",
    "adapter_mismatch",
    "adapter_error",
    "invalid_adapter_result",
    "policy_denied",
    "policy_mismatch",
    "signer_unavailable",
    "signer_invalid",
]
type Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


# A reference is an opaque local identifier, not a URL, path, query, token, or
# provider configuration.  In particular, ``/``, ``?``, ``#``, ``@`` and ``%``
# are intentionally absent from the grammar.  The semantic validator also
# rejects common secret/query labels so an opaque reference cannot be used as a
# convenient bearer-token or provider-config escape hatch.
def _safe_opaque_ref(value: str) -> str:
    lowered = value.casefold()
    if any(
        term in lowered
        for term in (
            "secret",
            "token",
            "bearer",
            "password",
            "api_key",
            "query",
            "http",
        )
    ):
        raise ValueError("opaque reference contains a forbidden sensitive term")
    return value


type OpaqueRef = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    ),
    AfterValidator(_safe_opaque_ref),
]
type Signature = Annotated[
    str,
    Field(
        min_length=1,
        max_length=2_048,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


class ArtifactPolicy(ProtocolModel):
    """The complete policy inherited by every certification report artifact."""

    schema_version: Literal["data-quality-policy.v1"]
    tenant_ref: OpaqueRef
    classification: DataClassification
    retention_policy_ref: OpaqueRef
    deletion_policy_ref: OpaqueRef
    access_policy_ref: OpaqueRef


class AuthorizedArrowSample(ProtocolModel):
    """An explicit, bounded authorization for one in-memory Arrow sample."""

    schema_version: Literal["data-quality-sample.v1"]
    sample_artifact_ref: OpaqueRef
    authorization_ref: OpaqueRef
    policy: ArtifactPolicy
    expires_at_ms: int = Field(ge=1)
    max_rows: int = Field(ge=1, le=1_000_000)
    max_columns: int = Field(ge=1, le=1_024)
    max_bytes: int = Field(ge=1, le=512 * 1024 * 1024)


class CertificationJobSpec(ProtocolModel):
    """Operator job identity and provider contract binding."""

    schema_version: Literal["data-quality-job.v1"]
    job_ref: OpaqueRef
    backend: CertificationBackend
    contract_ref: OpaqueRef
    sample: AuthorizedArrowSample


class CertificationArtifact(ProtocolModel):
    """An already-published, access-controlled human report reference."""

    schema_version: Literal["data-quality-report.v1"]
    artifact_ref: OpaqueRef
    media_type: Literal["text/html", "application/json"]
    content_digest: Digest
    byte_size: int = Field(ge=1, le=4 * 1024 * 1024)
    policy: ArtifactPolicy


class AdapterObservation(ProtocolModel):
    """Bounded provider outcome; no provider exception or result body is allowed."""

    schema_version: Literal["data-quality-observation.v1"]
    status: Literal["failed", "passed"]
    provider_version: OpaqueRef
    checks_total: int = Field(ge=0, le=10_000)
    checks_passed: int = Field(ge=0, le=10_000)
    checks_failed: int = Field(ge=0, le=10_000)
    failure_codes: list[FailureCode] = Field(default_factory=list, max_length=8)
    report: CertificationArtifact | None = None

    @model_validator(mode="after")
    def counts_and_status_are_consistent(self) -> AdapterObservation:
        if self.checks_total != self.checks_passed + self.checks_failed:
            raise ValueError("quality check counts must reconcile")
        if self.status == "passed" and self.checks_total == 0:
            raise ValueError("a passed result must contain at least one check")
        if self.status == "passed" and (self.checks_failed or self.failure_codes):
            raise ValueError("a passed observation cannot contain failures")
        if self.status == "failed" and not (self.checks_failed or self.failure_codes):
            raise ValueError("a failed observation must identify a bounded failure")
        return self


class SignedResultSummary(ProtocolModel):
    """The only durable result body emitted by the optional certification job."""

    schema_version: Literal["data-quality-result.v1"]
    job_ref: OpaqueRef
    backend: CertificationBackend
    contract_ref: OpaqueRef
    sample_artifact_ref: OpaqueRef
    policy: ArtifactPolicy
    status: Literal["failed", "passed"]
    checks_total: int = Field(ge=0, le=10_000)
    checks_passed: int = Field(ge=0, le=10_000)
    checks_failed: int = Field(ge=0, le=10_000)
    failure_codes: list[FailureCode] = Field(default_factory=list, max_length=8)
    report_artifact_ref: OpaqueRef | None = None
    report_content_digest: Digest | None = None
    report_byte_size: int | None = Field(default=None, ge=1, le=4 * 1024 * 1024)
    summary_digest: Digest
    signer_ref: OpaqueRef
    signature_algorithm: Literal["ed25519"]
    signature: Signature

    @model_validator(mode="after")
    def counts_and_status_are_consistent(self) -> SignedResultSummary:
        if self.checks_total != self.checks_passed + self.checks_failed:
            raise ValueError("signed quality check counts must reconcile")
        _check_status_failures(self)
        _check_report_fields(self)
        return self


def _check_status_failures(summary: SignedResultSummary) -> None:
    has_failures = bool(summary.checks_failed or summary.failure_codes)
    if summary.status == "passed" and summary.checks_total == 0:
        raise ValueError("a passed result must contain at least one check")
    if summary.status == "passed" and has_failures:
        raise ValueError("a signed passed result cannot contain failures")
    if summary.status == "failed" and not has_failures:
        raise ValueError("a signed failed result must identify a bounded failure")


def _check_report_fields(summary: SignedResultSummary) -> None:
    has_digest = summary.report_content_digest is not None
    has_size = summary.report_byte_size is not None
    if summary.report_artifact_ref is None and (has_digest or has_size):
        raise ValueError("report digest/size requires a report reference")
    if summary.report_artifact_ref is not None and not (has_digest and has_size):
        raise ValueError("report reference requires its digest and byte size")


class CertificationResult(ProtocolModel):
    """Honest terminal state for requested and non-requested optional work."""

    schema_version: Literal["data-quality-result-state.v1"]
    job_ref: OpaqueRef
    state: CertificationState
    failure_code: FailureCode | None = None
    report: CertificationArtifact | None = None
    signed_summary: SignedResultSummary | None = None

    @model_validator(mode="after")
    def references_match(self) -> CertificationResult:
        if self.report is not None and self.signed_summary is None:
            raise ValueError("a report reference requires a signed summary")
        if self.signed_summary is not None:
            _check_signed_summary_links(self, self.signed_summary)
        if self.state == "passed" and self.signed_summary is None:
            raise ValueError("passed certification requires a signed summary")
        if self.state in {"not_requested", "unavailable", "denied"} and (
            self.report is not None or self.signed_summary is not None
        ):
            raise ValueError("non-executed certification cannot publish artifacts")
        return self


def _check_signed_summary_links(
    result: CertificationResult, summary: SignedResultSummary
) -> None:
    if result.state not in {"failed", "passed"}:
        raise ValueError("only executed states may carry a signed summary")
    if result.state != summary.status:
        raise ValueError("certification state must match signed summary status")
    report = result.report
    if report is not None and report.artifact_ref != summary.report_artifact_ref:
        raise ValueError("report and signed summary references differ")
    if report is not None and (
        report.content_digest != summary.report_content_digest
        or report.byte_size != summary.report_byte_size
    ):
        raise ValueError("report and signed summary digests differ")
    if summary.job_ref != result.job_ref:
        raise ValueError("signed summary job reference differs")


__all__ = [
    "AdapterObservation",
    "ArtifactPolicy",
    "AuthorizedArrowSample",
    "CertificationArtifact",
    "CertificationBackend",
    "CertificationJobSpec",
    "CertificationResult",
    "CertificationState",
    "Digest",
    "FailureCode",
    "OpaqueRef",
    "Signature",
    "SignedResultSummary",
]
