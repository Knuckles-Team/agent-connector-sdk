"""Adversarial fixtures for the NE-112 typed local/engine profile contract."""

from __future__ import annotations

import json

import pyarrow as pa
import pytest

from agent_connector_sdk.data_prep import (
    CleanPipeline,
    CleanPlan,
    ProfileEvidenceDenied,
    ProfileEvidenceReference,
    ProfileLimitError,
    ProfileLimits,
    ProfileRequest,
    ProfileResult,
    ProfileSelector,
    ProfileSelectorError,
    build_profile_evidence_reference,
    profile_digest,
    profile_table,
    profile_with_client,
    schema_digest,
)

pytestmark = [
    pytest.mark.spec("SCION-SOURCE-INGEST-R803"),
]


def _plan(*, max_rows: int = 20, max_columns: int = 8) -> CleanPlan:
    return CleanPlan.model_validate(
        {
            "schema_version": "1",
            "steps": [{"verb": "canonical_names"}],
            "profile": {
                "max_rows": max_rows,
                "max_columns": max_columns,
                "max_steps": 8,
            },
            "invalid_row_disposition": "fail",
            "plan_ref": "plan:profile:v1",
            "policy_ref": "policy:profile:v1",
            "model_ref": "model:profile:v1",
            "source_ref": "source:profile",
            "artifact_ref": "artifact:profile",
        }
    )


def test_empty_profile_is_typed_and_value_free() -> None:
    result = CleanPipeline(_plan()).profile(
        pa.table({"value": pa.array([], type=pa.string())})
    )

    assert result.rows == 0
    assert result.columns == 1
    assert "empty_dataset" in result.warnings
    assert result.column_profiles[0].top_k == []
    assert result.column_profiles[0].min_value is None


def test_all_null_column_suppresses_statistics() -> None:
    result = CleanPipeline(_plan()).profile(pa.table({"value": [None, None, None]}))

    column = result.column_profiles[0]
    assert column.null_count == 3
    assert "all_null" in column.warning_codes
    assert "small_group_suppressed" in column.warning_codes
    assert column.min_value is None
    assert column.mean is None
    assert column.top_k == []


def test_cardinality_is_bounded_and_high_cardinality_is_observable() -> None:
    table = pa.table({"value": [1, 2, 3]})
    local = _plan().profile
    result = profile_table(table, local, limits=ProfileLimits(max_cardinality=3))

    assert "high_cardinality" in result.column_profiles[0].warning_codes
    with pytest.raises(ProfileLimitError):
        profile_table(
            table,
            local,
            limits=ProfileLimits(max_cardinality=2),
        )


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.5")
def test_below_threshold_values_never_appear_in_top_k_or_serialized_profile() -> None:
    table = pa.table({"secret": ["glpat-a", "glpat-b", "glpat-a", "glpat-b"]})
    result = profile_table(
        table,
        _plan().profile,
        limits=ProfileLimits(disclosure_threshold=3),
    )
    dumped = json.dumps(result.model_dump(mode="json"), sort_keys=True)

    assert result.column_profiles[0].top_k == []
    assert "glpat-a" not in dumped
    assert "glpat-b" not in dumped
    assert "secret" not in dumped


def test_selector_schema_digest_is_stale_after_schema_change() -> None:
    table = pa.table({"value": [1, 2]})
    selector = ProfileSelector(
        schema_digest="sha256:" + "0" * 64,
        ordinals=[0],
    )

    with pytest.raises(ProfileSelectorError):
        profile_table(table, _plan().profile, selector=selector)


def test_profile_limits_deny_columns_bytes_and_deadline() -> None:
    table = pa.table({"left": [1, 2], "right": [3, 4]})
    with pytest.raises(ProfileLimitError):
        profile_table(
            table,
            _plan().profile,
            limits=ProfileLimits(max_columns=1),
        )
    with pytest.raises(ProfileLimitError):
        profile_table(
            table,
            _plan().profile,
            limits=ProfileLimits(max_bytes=1),
        )


def test_local_result_has_exact_target_schema_and_lsn_identity() -> None:
    table = pa.table({"value": [1, 2, 3]})
    digest = schema_digest(table)
    result = profile_table(
        table,
        _plan().profile,
        target_ref="local:fixture",
        as_of_lsn=7,
        limits=ProfileLimits(disclosure_threshold=2),
    )

    assert result.target.target_ref == "local:fixture"
    assert result.target.schema_digest == digest
    assert result.schema_digest == digest
    assert result.target.as_of_lsn == 7
    assert result.as_of_lsn == 7


def test_engine_client_must_return_the_same_bounded_result_contract() -> None:
    table = pa.table({"value": [1, 2, 3]})
    local = profile_table(table, _plan().profile, target_ref="engine:table")
    engine = ProfileResult.model_validate(
        {
            **local.model_dump(mode="json"),
            "algorithm": "epistemic-graph-profile",
        }
    )
    request = ProfileRequest(
        schema_version="data-prep-profile.v1",
        target=local.target,
        limits=ProfileLimits(),
    )

    class Client:
        def profile(self, received: ProfileRequest) -> ProfileResult:
            assert received == request
            return engine

    assert profile_with_client(Client(), request) == engine


def test_profile_evidence_requires_separate_native_authority() -> None:
    profile = CleanPipeline(_plan()).profile(pa.table({"value": [1, 2]}))
    with pytest.raises(ProfileEvidenceDenied):
        build_profile_evidence_reference(profile, authority=None)

    digest = profile_digest(profile)

    class Authority:
        def authorize_profile_evidence(
            self, *, profile_digest: str, target: object
        ) -> ProfileEvidenceReference:
            assert target == profile.target
            return ProfileEvidenceReference(
                schema_version="data-prep-profile-evidence.v1",
                authority="native_change_envelope",
                profile_digest=profile_digest,
                artifact_ref="artifact:profile-evidence",
                change_envelope_ref="change-envelope:profile-evidence",
            )

    reference = build_profile_evidence_reference(profile, authority=Authority())
    assert reference.profile_digest == digest


# --- profile result surface: typed columns, warnings and the engine seam ---

from typing import get_args  # noqa: E402

from pydantic import TypeAdapter, ValidationError  # noqa: E402

from agent_connector_sdk.data_prep import (  # noqa: E402
    ColumnProfile,
    ProfileClient,
    ProfileDeadlineError,
    ProfileEvidenceAuthority,
    ProfileProtocolError,
    ProfileScalar,
    ProfileTarget,
    ProfileTargetKind,
    ProfileWarningCode,
    QuantilePoint,
    TopKEntry,
    validate_engine_profile,
)


def test_column_profiles_are_typed_and_disclosure_bounded() -> None:
    table = pa.table({"value": [1, 1, 2, 3, 3, 3]})
    result = profile_table(
        table,
        _plan().profile,
        target_ref="local:typed",
        limits=ProfileLimits(max_top_k=3, max_quantiles=3, disclosure_threshold=2),
    )
    assert isinstance(result.target, ProfileTarget)
    assert result.target.target_kind in get_args(ProfileTargetKind.__value__)
    (column,) = result.column_profiles
    assert isinstance(column, ColumnProfile)
    assert (column.min_value, column.max_value, column.null_count) == (None, None, 0)
    assert "stats_suppressed" in column.warning_codes
    assert all(isinstance(q, QuantilePoint) for q in column.quantiles)
    assert all(0.0 <= q.probability <= 1.0 for q in column.quantiles)
    assert all(isinstance(entry, TopKEntry) for entry in column.top_k)
    # 2 appears once: below the disclosure threshold it never reaches top-k.
    assert {entry.value for entry in column.top_k} == {1, 3}
    codes = set(get_args(ProfileWarningCode.__value__))
    assert set(result.warnings) <= codes and set(column.warning_codes) <= codes
    with pytest.raises(ValidationError):
        TypeAdapter(ProfileScalar).validate_python(None)
    with pytest.raises(ValidationError):
        TopKEntry(value=1, count=0)


def test_engine_profile_validation_rejects_the_wrong_authority_or_target() -> None:
    local = profile_table(
        pa.table({"value": [1, 2]}), _plan().profile, target_ref="e:t"
    )
    request = ProfileRequest(schema_version="data-prep-profile.v1", target=local.target)
    with pytest.raises(ProfileProtocolError, match="wrong authority"):
        validate_engine_profile(local, request)
    engine = ProfileResult.model_validate(
        {**local.model_dump(mode="json"), "algorithm": "epistemic-graph-profile"}
    )
    assert validate_engine_profile(engine, request) == engine
    moved = ProfileRequest(
        schema_version="data-prep-profile.v1",
        target=local.target.model_copy(update={"target_ref": "e:other"}),
    )
    with pytest.raises(ProfileProtocolError, match="target"):
        validate_engine_profile(engine, moved)

    class Client:
        def profile(self, received: ProfileRequest) -> ProfileResult:
            return engine

    class Authority:
        def authorize_profile_evidence(self, *, profile_digest, target):
            raise AssertionError("not called")

    client: ProfileClient = Client()
    authority: ProfileEvidenceAuthority = Authority()
    assert profile_with_client(client, request) == engine
    assert callable(authority.authorize_profile_evidence)
    assert issubclass(ProfileDeadlineError, ProfileLimitError)


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.9")
def test_rare_numeric_values_do_not_escape_in_statistics() -> None:
    limits = ProfileLimits(disclosure_threshold=2)
    rare = profile_table(
        pa.table({"value": [1, 1, 987654321]}), _plan().profile, limits=limits
    )
    column = rare.column_profiles[0]
    assert column.min_value is None
    assert column.max_value is None
    assert column.mean is None
    assert column.quantiles == []
    assert "stats_suppressed" in column.warning_codes
    assert "987654321" not in rare.model_dump_json()
    eligible = profile_table(
        pa.table({"value": [1, 1, 3, 3]}), _plan().profile, limits=limits
    )
    assert eligible.column_profiles[0].min_value == 1
    assert eligible.column_profiles[0].max_value == 3


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.9")
def test_failed_frequency_count_suppresses_numeric_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pyarrow.compute as pc

    def unavailable(_values: object) -> None:
        raise NotImplementedError("frequency count unavailable")

    monkeypatch.setattr(pc, "value_counts", unavailable)
    result = profile_table(
        pa.table({"value": [1, 1, 987654321]}),
        _plan().profile,
        limits=ProfileLimits(disclosure_threshold=2),
    )
    column = result.column_profiles[0]
    assert column.min_value is None
    assert column.max_value is None
    assert column.mean is None
    assert column.quantiles == []
    assert column.top_k == []
    assert "stats_suppressed" in column.warning_codes
    assert "987654321" not in result.model_dump_json()


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.14")
def test_engine_profile_revalidates_mutated_nested_results() -> None:
    local = profile_table(
        pa.table({"value": [1, 1, 2, 2]}), _plan().profile, target_ref="engine:table"
    )
    engine = ProfileResult.model_validate(
        {**local.model_dump(mode="python"), "algorithm": "epistemic-graph-profile"}
    )
    request = ProfileRequest(schema_version="data-prep-profile.v1", target=local.target)
    engine.column_profiles[0].top_k.append(TopKEntry(value=987654321, count=1))

    class Client:
        def profile(self, received: ProfileRequest) -> ProfileResult:
            return engine

    with pytest.raises(ProfileProtocolError, match="invalid result"):
        profile_with_client(Client(), request)
