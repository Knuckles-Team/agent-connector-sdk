"""Bounded operator certification job orchestration.

``run_certification_job`` is the only execution helper in this package.  It
accepts an already-authorized in-memory Arrow sample, applies the authorization
limits before provider code runs, invokes one lazy optional adapter, and emits
only an opaque report reference plus a signed aggregate result.  It never calls
``ChangeEnvelope``/``MutationBatch``, writes graph facts, or changes an engine
decision retroactively.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from scion_sdk.data_prep.kernel import (
    ArrowAdapter,
    DataPrepDependencyError,
    ProfileLimitError,
)
from scion_sdk.data_prep.models import LocalProfile

from ._signing import (
    CertificationSigner,
    _result,
    _signed_failure,
    _signed_result,
    _Terminal,
)
from .adapters import CertificationAdapter, CertificationDependencyUnavailable
from .models import (
    AdapterObservation,
    CertificationJobSpec,
    CertificationResult,
    CertificationState,
    FailureCode,
)

__all__ = [
    "CertificationSigner",
    "mark_not_requested",
    "run_certification_job",
]


def mark_not_requested(job: CertificationJobSpec) -> CertificationResult:
    """Return an honest absence state when an operator did not request a run."""

    return _result(job, "not_requested")


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
    *,
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
    *,
    adapter: CertificationAdapter,
    signer: CertificationSigner | None,
    now_ms: int | None,
) -> CertificationResult:
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if current_ms >= job.sample.expires_at_ms:
        return _result(job, "denied", failure_code="authorization_expired")
    if str(getattr(adapter, "backend", "")) != job.backend:
        return _result(job, "denied", failure_code="adapter_mismatch")
    observation = _observe(
        _bounded_table(table, job), job, adapter=adapter, signer=signer
    )
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
        return _run_stages(table, job, adapter=adapter, signer=signer, now_ms=now_ms)
    except _Terminal as terminal:
        return terminal.result
