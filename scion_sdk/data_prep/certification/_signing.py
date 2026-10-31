"""Signing, digesting and terminal-result helpers for certification jobs."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from .models import (
    AdapterObservation,
    CertificationJobSpec,
    CertificationResult,
    CertificationState,
    FailureCode,
    SignedResultSummary,
)


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
    *,
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
        summary = _signed_summary(job, observation, signer=signer, identity=identity)
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
