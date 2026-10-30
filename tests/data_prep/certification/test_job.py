"""Focused NE-114 policy, privacy, and optional-adapter fixtures."""

from __future__ import annotations

import subprocess
import sys

import pytest
from pydantic import ValidationError

pa = pytest.importorskip(
    "pyarrow",
    reason="NE-114 Arrow contract requires the explicit [dataprep] extra",
)

from scion_sdk.data_prep._classification import (  # noqa: E402
    DataClassification,
)
from scion_sdk.data_prep.certification import (  # noqa: E402
    AdapterObservation,
    ArtifactPolicy,
    AuthorizedArrowSample,
    CertificationArtifact,
    CertificationDependencyUnavailable,
    CertificationJobSpec,
    CertificationResult,
    GreatExpectationsAdapter,
    SignedResultSummary,
    run_certification_job,
)

pytestmark = [
    pytest.mark.spec("SCION-SOURCE-INGEST-R803"),
]


class _Signer:
    signer_id = "fixture-signer"
    algorithm = "ed25519"

    def sign(self, _digest_hex: str) -> str:
        return "fixture-signature"


def _policy(*, tenant_ref: str = "tenant-fixture") -> ArtifactPolicy:
    return ArtifactPolicy(
        schema_version="data-quality-policy.v1",
        tenant_ref=tenant_ref,
        classification=DataClassification.INTERNAL,
        retention_policy_ref="retention:p7d",
        deletion_policy_ref="deletion:tenant",
        access_policy_ref="acl:operator",
    )


def _job(*, policy: ArtifactPolicy | None = None, expires_at_ms: int = 10_000):
    return CertificationJobSpec(
        schema_version="data-quality-job.v1",
        job_ref="job:fixture",
        backend="great_expectations",
        contract_ref="contract:fixture",
        sample=AuthorizedArrowSample(
            schema_version="data-quality-sample.v1",
            sample_artifact_ref="sample:fixture",
            authorization_ref="grant:fixture",
            policy=policy or _policy(),
            expires_at_ms=expires_at_ms,
            max_rows=8,
            max_columns=4,
            max_bytes=64 * 1024,
        ),
    )


def _report(policy: ArtifactPolicy) -> CertificationArtifact:
    return CertificationArtifact(
        schema_version="data-quality-report.v1",
        artifact_ref="report:fixture",
        media_type="application/json",
        content_digest="sha256:" + "a" * 64,
        byte_size=128,
        policy=policy,
    )


class _PassingAdapter:
    backend = "great_expectations"

    def __init__(self, report: CertificationArtifact | None) -> None:
        self.report = report

    def run(self, _table, *, authorization):
        return AdapterObservation(
            schema_version="data-quality-observation.v1",
            status="passed",
            provider_version="1.0.0",
            checks_total=2,
            checks_passed=2,
            checks_failed=0,
            report=self.report,
        )


def test_success_publishes_only_policy_bound_reference_and_signed_summary() -> None:
    job = _job()
    result = run_certification_job(
        pa.table({"id": [1, 2]}),
        job,
        adapter=_PassingAdapter(_report(job.sample.policy)),
        signer=_Signer(),
        now_ms=1_000,
    )

    assert result.state == "passed"
    assert result.report is not None
    assert result.report.artifact_ref == "report:fixture"
    assert result.report.policy == job.sample.policy
    assert result.signed_summary is not None
    assert result.signed_summary.report_artifact_ref == "report:fixture"
    assert result.signed_summary.report_content_digest == "sha256:" + "a" * 64
    assert result.signed_summary.report_byte_size == 128
    rendered = result.model_dump_json()
    assert "fixture-signature" in rendered
    assert "secret" not in rendered
    assert "bearer" not in rendered


def test_policy_mismatch_is_failed_and_does_not_publish_reference() -> None:
    job = _job()
    wrong_policy = _policy(tenant_ref="other-tenant")
    result = run_certification_job(
        pa.table({"id": [1]}),
        job,
        adapter=_PassingAdapter(_report(wrong_policy)),
        signer=_Signer(),
        now_ms=1_000,
    )

    assert result.state == "failed"
    assert result.failure_code == "policy_mismatch"
    assert result.report is None
    assert result.signed_summary is not None
    assert result.signed_summary.report_artifact_ref is None


def test_provider_absence_is_honest_and_exception_detail_is_not_evidence() -> None:
    class _UnavailableAdapter:
        backend = "great_expectations"

        def run(self, _table, *, authorization):
            raise CertificationDependencyUnavailable("bearer token must not escape")

    result = run_certification_job(
        pa.table({"id": [1]}),
        _job(),
        adapter=_UnavailableAdapter(),
        signer=_Signer(),
        now_ms=1_000,
    )

    assert result.state == "unavailable"
    assert result.failure_code == "provider_dependency_unavailable"
    assert result.signed_summary is None
    assert "bearer" not in result.model_dump_json()


def test_expired_authorization_and_unsafe_references_fail_closed() -> None:
    expired = run_certification_job(
        pa.table({"id": [1]}),
        _job(expires_at_ms=1_000),
        adapter=_PassingAdapter(None),
        signer=_Signer(),
        now_ms=1_000,
    )
    assert expired.state == "denied"
    assert expired.failure_code == "authorization_expired"

    with pytest.raises(ValidationError):
        _policy(tenant_ref="https://provider.example/query?token=secret")


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.3")
def test_optional_provider_wrappers_are_lazy_and_do_not_run_without_provider() -> None:
    # A clean interpreter proves the certification package itself does not pull
    # optional provider runtimes into the base import path.
    probe = (
        "import sys; "
        "import scion_sdk.data_prep.certification; "
        "roots = {name.split('.', 1)[0] for name in sys.modules}; "
        "forbidden = {'great_expectations', 'pandera', 'pandas', 'numpy', 'pyarrow'}; "
        "assert not roots & forbidden, sorted(roots & forbidden)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    # Construction itself must not import either optional provider.  The runner
    # is deliberately never reached in this fixture.
    adapter = GreatExpectationsAdapter(lambda _table, _authorization: {})
    assert adapter.backend == "great_expectations"


# --- typed result surface: states, signer seam and the Pandera wrapper ---

from typing import get_args  # noqa: E402

from pydantic import TypeAdapter  # noqa: E402

from scion_sdk.data_prep.certification import (  # noqa: E402
    CertificationAdapter,
    CertificationBackend,
    CertificationSigner,
    CertificationState,
    FailureCode,
    PanderaAdapter,
    mark_not_requested,
)
from scion_sdk.data_prep.certification.models import (  # noqa: E402
    OpaqueRef,
    Signature,
)


def test_not_requested_is_an_honest_state_without_artifacts() -> None:
    result = mark_not_requested(_job())
    assert isinstance(result, CertificationResult)
    assert result.state == "not_requested"
    assert result.state in get_args(CertificationState.__value__)
    assert (result.report, result.signed_summary) == (None, None)


def test_signed_summary_binds_signer_and_backend() -> None:
    signer: CertificationSigner = _Signer()
    adapter: CertificationAdapter = _PassingAdapter(None)
    result = run_certification_job(
        pa.table({"id": [1]}), _job(), adapter=adapter, signer=signer, now_ms=1_000
    )
    summary = result.signed_summary
    assert isinstance(summary, SignedResultSummary)
    assert (summary.signer_ref, summary.signature) == (
        "fixture-signer",
        "fixture-signature",
    )
    assert summary.backend in get_args(CertificationBackend.__value__)
    assert set(summary.failure_codes) <= set(get_args(FailureCode.__value__))

    class _WrongAlgorithm(_Signer):
        algorithm = "rsa"

    denied = run_certification_job(
        pa.table({"id": [1]}),
        _job(),
        adapter=adapter,
        signer=_WrongAlgorithm(),
        now_ms=1_000,
    )
    assert (denied.state, denied.failure_code) == ("failed", "signer_invalid")


def test_reference_aliases_reject_unsafe_values_and_pandera_is_lazy() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(OpaqueRef).validate_python("https://x.example/?token=secret")
    with pytest.raises(ValidationError):
        TypeAdapter(Signature).validate_python("")
    assert PanderaAdapter(lambda _table, _authorization: {}).backend == "pandera"


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.10")
def test_empty_pass_is_refused() -> None:
    empty = {
        "schema_version": "data-quality-observation.v1",
        "status": "passed",
        "provider_version": "1.0.0",
        "checks_total": 0,
        "checks_passed": 0,
        "checks_failed": 0,
    }
    with pytest.raises(ValidationError, match="at least one check"):
        AdapterObservation.model_validate(empty)

    class EmptyAdapter:
        backend = "great_expectations"

        def run(self, _table, *, authorization):
            return AdapterObservation.model_construct(**empty)

    result = run_certification_job(
        pa.table({"id": [1]}),
        _job(),
        adapter=EmptyAdapter(),
        signer=_Signer(),
        now_ms=1_000,
    )
    assert result.state == "failed"
    assert result.failure_code == "invalid_adapter_result"
    assert result.signed_summary is not None
    assert result.signed_summary.status == "failed"
    forged = result.signed_summary.model_dump(mode="python")
    forged.update(status="passed", failure_codes=[])
    with pytest.raises(ValidationError, match="at least one check"):
        SignedResultSummary.model_validate(forged)


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.11")
@pytest.mark.parametrize("state", ["passed", "failed"])
def test_result_rejects_mismatched_signed_status(state: str) -> None:
    job = _job()
    passed = run_certification_job(
        pa.table({"id": [1]}),
        job,
        adapter=_PassingAdapter(None),
        signer=_Signer(),
        now_ms=1_000,
    )

    class FailureAdapter:
        backend = "great_expectations"

        def run(self, _table, *, authorization):
            raise ValueError("provider failure")

    failed = run_certification_job(
        pa.table({"id": [1]}),
        job,
        adapter=FailureAdapter(),
        signer=_Signer(),
        now_ms=1_000,
    )
    summary = failed.signed_summary if state == "passed" else passed.signed_summary
    assert summary is not None
    with pytest.raises(ValidationError, match="state must match"):
        CertificationResult.model_validate(
            {
                "schema_version": "data-quality-result-state.v1",
                "job_ref": job.job_ref,
                "state": state,
                "signed_summary": summary,
            }
        )


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.12")
@pytest.mark.parametrize("field", ["signer_id", "algorithm", "signature"])
@pytest.mark.parametrize("value", [None, 123, b"signature"])
def test_nonstring_signer_output_is_refused(field: str, value: object) -> None:
    class InvalidSigner:
        signer_id = "fixture-signer"
        algorithm = "ed25519"

        def sign(self, _digest_hex):
            return value if field == "signature" else "fixture-signature"

    signer = InvalidSigner()
    if field != "signature":
        setattr(signer, field, value)
    result = run_certification_job(
        pa.table({"id": [1]}),
        _job(),
        adapter=_PassingAdapter(None),
        signer=signer,
        now_ms=1_000,
    )
    assert result.state == "failed"
    assert result.failure_code == "signer_invalid"
    assert result.signed_summary is None
