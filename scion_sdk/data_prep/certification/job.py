"""Bounded operator certification job orchestration.

``run_certification_job`` is the only execution helper in this package.  It
accepts an already-authorized in-memory Arrow sample, applies the authorization
limits before provider code runs, invokes one lazy optional adapter, and emits
only an opaque report reference plus a signed aggregate result.  It never calls
``ChangeEnvelope``/``MutationBatch``, writes graph facts, or changes an engine
decision retroactively.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol

from pydantic import ValidationError

from scion_sdk.data_prep.kernel import (
    ArrowAdapter,
    DataPrepDependencyError,
    ProfileLimitError,
)
from scion_sdk.data_prep.models import LocalProfile

from .adapters import CertificationAdapter, CertificationDependencyUnavailable
from .models import (
    AdapterObservation,
    CertificationJobSpec,
    CertificationResult,
    CertificationState,
    FailureCode,
    SignedResultSummary,
)

__all__ = [
    "CertificationSigner",
    "mark_not_requested",
    "run_certification_job",
]


class CertificationSigner(Protocol):
    """Operator-provided Ed25519 signer; private key custody stays external."""

    signer_id: str
    algorithm: str

    def sign(self, digest_hex: str) -> str: ...


def _digest(value: dict[str, Any]) -> tuple[str, str]:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest_hex = hashlib.sha256(payload).hexdigest()
    return f"sha256:{digest_hex}", digest_hex


def _result(
    job: CertificationJobSpec,
    state: CertificationState,
    *,
    failure_code: FailureCode | None = None,
) -> CertificationResult:
    return CertificationResult(
        schema_version="data-quality-result-state.v1",
        job_ref=job.job_ref,
        state=state,
        failure_code=failure_code,
    )


def mark_not_requested(job: CertificationJobSpec) -> CertificationResult:
    """Return an honest absence state when an operator did not request a run."""

    return _result(job, "not_requested")


class _Terminal(Exception):
    """Carry an already-built terminal result out of a job stage."""

    def __init__(self, result: CertificationResult) -> None:
        super().__init__()
        self.result = result


def _signer_identity(signer: object) -> tuple[str, str] | None:
    signer_id = getattr(signer, "signer_id", None)
    algorithm = getattr(signer, "algorithm", None)
    if not isinstance(signer_id, str) or not isinstance(algorithm, str):
        return None
    if not signer_id or algorithm != "ed25519":
        return None
    return signer_id, algorithm


def _unsigned_summary(
    job: CertificationJobSpec,
    observation: AdapterObservation,
    identity: tuple[str, str],
) -> dict[str, Any]:
    report = observation.report
    return {
        "schema_version": "data-quality-result.v1",
        "job_ref": job.job_ref,
        "backend": job.backend,
        "contract_ref": job.contract_ref,
        "sample_artifact_ref": job.sample.sample_artifact_ref,
        "policy": job.sample.policy.model_dump(mode="json"),
        "status": observation.status,
        "checks_total": observation.checks_total,
        "checks_passed": observation.checks_passed,
        "checks_failed": observation.checks_failed,
        "failure_codes": list(observation.failure_codes),
        "report_artifact_ref": report.artifact_ref if report else None,
        "report_content_digest": report.content_digest if report else None,
        "report_byte_size": report.byte_size if report else None,
        "signer_ref": identity[0],
        "signature_algorithm": identity[1],
    }


def _signed_summary(
    job: CertificationJobSpec,
    observation: AdapterObservation,
    signer: CertificationSigner,
    identity: tuple[str, str],
) -> SignedResultSummary:
    unsigned = _unsigned_summary(job, observation, identity)
    summary_digest, digest_hex = _digest(unsigned)
    try:
        signature: object = signer.sign(digest_hex)
    except Exception:
        raise _Terminal(
            _result(job, "failed", failure_code="signer_unavailable")
        ) from None
    try:
        if not isinstance(signature, str):
            raise TypeError("signature must be a string")
        return SignedResultSummary(
            **{**unsigned, "policy": job.sample.policy},
            summary_digest=summary_digest,
            signature=signature,
        )
    except Exception:
        raise _Terminal(_result(job, "failed", failure_code="signer_invalid")) from None


def _signed_result(
    job: CertificationJobSpec,
    observation: AdapterObservation,
    signer: CertificationSigner,
) -> CertificationResult:
    identity = _signer_identity(signer)
    if identity is None:
        return _result(job, "failed", failure_code="signer_invalid")
    try:
        summary = _signed_summary(job, observation, signer, identity)
    except _Terminal as terminal:
        return terminal.result
    return CertificationResult(
        schema_version="data-quality-result-state.v1",
        job_ref=job.job_ref,
        state=observation.status,
        failure_code=(
            observation.failure_codes[0] if observation.failure_codes else None
        ),
        report=observation.report,
        signed_summary=summary,
    )


def _signed_failure(
    job: CertificationJobSpec,
    failure_code: FailureCode,
    signer: CertificationSigner | None,
) -> CertificationResult:
    """Sign an executed failure without carrying provider detail or a report."""

    if signer is None:
        return _result(job, "failed", failure_code="signer_unavailable")
    observation = AdapterObservation(
        schema_version="data-quality-observation.v1",
        status="failed",
        provider_version="unknown",
        checks_total=0,
        checks_passed=0,
        checks_failed=0,
        failure_codes=[failure_code],
    )
    return _signed_result(job, observation, signer)


def _bounded_table(table: Any, job: CertificationJobSpec) -> Any:
    profile = LocalProfile(
        max_rows=job.sample.max_rows,
        max_columns=job.sample.max_columns,
        max_steps=1,
        max_bytes=job.sample.max_bytes,
        max_outcome_rows=min(job.sample.max_rows, 100_000),
    )
    try:
        return ArrowAdapter.as_table(table, profile=profile)
    except DataPrepDependencyError:
        code: FailureCode = "arrow_dependency_unavailable"
        state: CertificationState = "unavailable"
    except ProfileLimitError:
        code, state = "sample_limit_exceeded", "denied"
    except (TypeError, ValueError):
        code, state = "invalid_sample", "denied"
    raise _Terminal(_result(job, state, failure_code=code))


def _observe(
    bounded_table: Any,
    job: CertificationJobSpec,
    adapter: CertificationAdapter,
    signer: CertificationSigner | None,
) -> AdapterObservation:
    try:
        observation: object = adapter.run(
            bounded_table,
            authorization=job.sample,
        )
    except CertificationDependencyUnavailable:
        raise _Terminal(
            _result(
                job,
                "unavailable",
                failure_code="provider_dependency_unavailable",
            )
        ) from None
    except Exception:
        raise _Terminal(_signed_failure(job, "adapter_error", signer)) from None
    invalid = _Terminal(_signed_failure(job, "invalid_adapter_result", signer))
    if not isinstance(observation, AdapterObservation):
        raise invalid
    try:
        return AdapterObservation.model_validate(observation.model_dump(mode="python"))
    except (ValidationError, TypeError, ValueError):
        raise invalid from None


def _run_stages(
    table: Any,
    job: CertificationJobSpec,
    adapter: CertificationAdapter,
    signer: CertificationSigner | None,
    now_ms: int | None,
) -> CertificationResult:
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if current_ms >= job.sample.expires_at_ms:
        return _result(job, "denied", failure_code="authorization_expired")
    if str(getattr(adapter, "backend", "")) != job.backend:
        return _result(job, "denied", failure_code="adapter_mismatch")
    observation = _observe(_bounded_table(table, job), job, adapter, signer)
    if (
        observation.report is not None
        and observation.report.policy != job.sample.policy
    ):
        # A report with weaker/different tenant governance is never returned,
        # even if the provider claims success.
        return _signed_failure(job, "policy_mismatch", signer)
    if signer is None:
        return _result(job, "failed", failure_code="signer_unavailable")
    return _signed_result(job, observation, signer)


def run_certification_job(
    table: Any,
    job: CertificationJobSpec,
    *,
    adapter: CertificationAdapter,
    signer: CertificationSigner | None,
    now_ms: int | None = None,
) -> CertificationResult:
    """Run one optional certification under an explicit Arrow sample policy.

    The caller must provide a signer.  A missing signer or provider is reported
    as an honest non-success and cannot produce an unsigned report reference.
    The ``now_ms`` injection keeps expiry checks deterministic for job tests.
    """

    try:
        return _run_stages(table, job, adapter, signer, now_ms)
    except _Terminal as terminal:
        return terminal.result
