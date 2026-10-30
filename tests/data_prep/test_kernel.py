"""Focused NE-108 tests for the bounded Arrow preparation kernel."""

from __future__ import annotations

import json
import resource
import time

import pyarrow as pa
import pytest
from pydantic import ConfigDict, ValidationError, create_model

from scion_sdk.data_prep import (
    CleanPipeline,
    CleanPlan,
    InvalidRowsError,
    PagedPrepResult,
    PlanExecutionError,
    PrepEvidence,
    ProfileLimitError,
    RowModelRegistry,
    row_model_digest,
)

pytestmark = [
    pytest.mark.spec("SCION-SOURCE-INGEST-R803"),
]


def _plan(*steps: dict[str, object], **overrides: object) -> CleanPlan:
    payload: dict[str, object] = {
        "schema_version": "1",
        "steps": list(steps) or [{"verb": "canonical_names"}],
        "profile": {
            "max_rows": 20,
            "max_columns": 8,
            "max_steps": 8,
        },
        "invalid_row_disposition": "fail",
        "plan_ref": "plan:data-prep:v1",
        "policy_ref": "policy:data-prep:v1",
        "model_ref": "model:test:v1",
        "source_ref": "source:test",
        "artifact_ref": "artifact:test",
    }
    payload.update(overrides)
    return CleanPlan.model_validate(payload)


def _row_model(model_name: str, **fields: object) -> type:
    """Build a strict test model with no executable import-path lookup."""

    return create_model(
        model_name,
        __config__=ConfigDict(strict=True, extra="forbid"),
        **{field: (annotation, ...) for field, annotation in fields.items()},
    )


def _registry(row_model: type) -> RowModelRegistry:
    return RowModelRegistry({"model:test:v1": row_model})


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.1")
def test_plan_gate_is_strict_and_allowlisted() -> None:
    with pytest.raises(ValidationError):
        CleanPipeline(
            {
                "schema_version": "1",
                "steps": [{"verb": "execute_python", "code": "secret"}],
                "profile": {"max_rows": 2, "max_columns": 2, "max_steps": 2},
                "invalid_row_disposition": "fail",
                "policy_ref": "policy:test",
            }
        )
    with pytest.raises(ValidationError):
        CleanPipeline(
            {
                "schema_version": "1",
                "steps": [{"verb": "dedupe", "keys": []}],
                "profile": {"max_rows": 2, "max_columns": 2, "max_steps": 2},
                "invalid_row_disposition": "fail",
                "policy_ref": "policy:test",
            }
        )
    with pytest.raises(ValidationError):
        CleanPipeline(
            {
                "schema_version": "1",
                "steps": [{"verb": "canonical_names", "unexpected": True}],
                "profile": {"max_rows": 2, "max_columns": 2, "max_steps": 2},
                "invalid_row_disposition": "fail",
                "policy_ref": "policy:test",
            }
        )
    with pytest.raises(ValidationError):
        CleanPipeline(
            {
                "schema_version": "1",
                "steps": [{"verb": "canonical_names"}],
                "profile": {"max_rows": "2", "max_columns": 2, "max_steps": 2},
                "invalid_row_disposition": "fail",
                "policy_ref": "policy:test",
            }
        )


@pytest.mark.parametrize(
    ("profile", "table"),
    [
        ({"max_rows": 1, "max_columns": 2, "max_steps": 2}, pa.table({"x": [1, 2]})),
        (
            {"max_rows": 2, "max_columns": 1, "max_steps": 2},
            pa.table({"x": [1, 2], "y": [3, 4]}),
        ),
        (
            {"max_rows": 2, "max_columns": 2, "max_steps": 2, "max_bytes": 1},
            pa.table({"x": [1, 2]}),
        ),
    ],
)
def test_profile_limits_are_enforced_before_execution(
    profile: dict[str, int], table: pa.Table
) -> None:
    plan = _plan(profile=profile)
    with pytest.raises(ProfileLimitError):
        CleanPipeline(
            plan,
            model_registry=_registry(
                _row_model("ProfileRow", **{name: int for name in table.column_names})
            ),
        ).run(table)


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.4")
def test_lossy_casts_are_denied_and_lossless_widening_uses_safe_cast() -> None:
    narrowing = _plan(
        {
            "verb": "safe_cast",
            "column": "value",
            "source_type": "int64",
            "target_type": "int32",
        }
    )
    with pytest.raises(PlanExecutionError):
        CleanPipeline(
            narrowing,
            model_registry=_registry(_row_model("NarrowingRow", value=int)),
        ).run(pa.table({"value": [1, 2]}))

    cross_family = _plan(
        {
            "verb": "safe_cast",
            "column": "value",
            "source_type": "int64",
            "target_type": "float64",
        }
    )
    with pytest.raises(PlanExecutionError):
        CleanPipeline(
            cross_family,
            model_registry=_registry(_row_model("CrossFamilyRow", value=int)),
        ).run(pa.table({"value": [1, 2]}))

    widening = _plan(
        {
            "verb": "safe_cast",
            "column": "value",
            "source_type": "int8",
            "target_type": "int64",
        }
    )
    result = CleanPipeline(
        widening,
        model_registry=_registry(_row_model("WideningRow", value=int)),
    ).run(pa.table({"value": pa.array([1, 2], type=pa.int8())}))
    assert result.table.schema.field("value").type == pa.int64()
    assert result.evidence.checkpoint_eligible


def test_fill_values_must_fit_the_arrow_type_without_loss() -> None:
    plan = _plan({"verb": "fill_nulls", "fills": {"value": 128}})
    with pytest.raises(PlanExecutionError):
        CleanPipeline(
            plan,
            model_registry=_registry(_row_model("FillRow", value=int)),
        ).run(pa.table({"value": pa.array([None], type=pa.int8())}))


def test_canonical_name_collision_fails_closed() -> None:
    plan = _plan({"verb": "canonical_names"})
    with pytest.raises(PlanExecutionError):
        CleanPipeline(
            plan,
            model_registry=_registry(_row_model("CollisionRow", value=int)),
        ).run(pa.table({"User ID": [1], "user_id": [2]}))


def test_quarantine_is_redacted_and_cannot_claim_checkpoint_success() -> None:
    plan = _plan(
        {"verb": "null_policy", "columns": ["email"], "action": "reject"},
        {"verb": "fill_nulls", "fills": {"email": "super-secret-fill"}},
        invalid_row_disposition="quarantine",
    )
    table = pa.table({"email": ["kept@example.test", None], "value": [1, 2]})
    result = CleanPipeline(
        plan,
        model_registry=_registry(_row_model("QuarantineRow", email=str, value=int)),
    ).run(table)

    assert result.table.num_rows == 1
    assert result.evidence.outcome == "quarantined"
    assert not result.evidence.checkpoint_eligible
    assert result.evidence.quarantined_rows == 1
    evidence_text = json.dumps(result.evidence.model_dump(), sort_keys=True)
    assert "super-secret-fill" not in evidence_text
    assert "kept@example.test" not in evidence_text
    assert "email" not in evidence_text

    with pytest.raises(ValidationError):
        PrepEvidence(
            **{
                **result.evidence.model_dump(),
                "checkpoint_eligible": True,
            }
        )


def test_strict_row_model_gate_emits_redacted_per_row_outcomes() -> None:
    plan = _plan(
        {"verb": "canonical_names"},
        invalid_row_disposition="quarantine",
    )
    table = pa.table({"value": pa.array(["not-an-int", "also-not-an-int"])})
    result = CleanPipeline(
        plan,
        model_registry=_registry(_row_model("StrictIntRow", value=int)),
    ).run(table)

    assert result.table.num_rows == 0
    assert result.evidence.model_rejected_rows == 2
    assert [item.status for item in result.evidence.row_outcomes] == [
        "quarantined",
        "quarantined",
    ]
    evidence_text = json.dumps(result.evidence.model_dump(), sort_keys=True)
    assert "not-an-int" not in evidence_text
    assert "also-not-an-int" not in evidence_text


def test_row_outcomes_retain_original_ordinals_across_quarantine_steps() -> None:
    plan = _plan(
        {"verb": "null_policy", "columns": ["value"], "action": "reject"},
        invalid_row_disposition="quarantine",
    )
    table = pa.table(
        {"value": pa.array(["1", None, "3", "not-an-int"], type=pa.string())}
    )
    result = CleanPipeline(
        plan,
        model_registry=_registry(_row_model("OriginalOrdinalRow", value=int)),
    ).run(table)

    assert [item.row_index for item in result.evidence.row_outcomes] == [0, 1, 2, 3]
    assert [item.reason_code for item in result.evidence.row_outcomes] == [
        "model_rejected",
        "null_rejected",
        "model_rejected",
        "model_rejected",
    ]


def test_row_model_must_be_strict_forbid_and_no_model_is_not_a_success() -> None:
    plan = _plan({"verb": "canonical_names"})
    with pytest.raises(PlanExecutionError):
        CleanPipeline(plan).run(pa.table({"value": [1]}))

    permissive = create_model(
        "PermissiveRow",
        __config__=ConfigDict(strict=False, extra="allow"),
        value=(int, ...),
    )
    with pytest.raises(PlanExecutionError):
        CleanPipeline(
            plan,
            model_registry=RowModelRegistry({"model:test:v1": permissive}),
        ).run(pa.table({"value": [1]}))


def test_model_registry_is_the_only_model_selection_authority() -> None:
    model = _row_model("ApprovedRow", value=int)
    registry = _registry(model)
    plan = _plan({"verb": "canonical_names"})
    result = CleanPipeline(plan, model_registry=registry).run(pa.table({"value": [1]}))
    assert result.evidence.model_ref == "model:test:v1"
    assert result.evidence.model_digest == row_model_digest(model)

    unknown_ref = _plan(
        {"verb": "canonical_names"},
        model_ref="model:unapproved:v1",
    )
    with pytest.raises(PlanExecutionError):
        CleanPipeline(unknown_ref, model_registry=registry).run(
            pa.table({"value": [1]})
        )

    mismatched_digest = _plan(
        {"verb": "canonical_names"},
        model_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(PlanExecutionError):
        CleanPipeline(mismatched_digest, model_registry=registry).run(
            pa.table({"value": [1]})
        )


def test_model_registry_rejects_mutated_model_schema() -> None:
    model = _row_model("MutableRow", value=int)
    registry = _registry(model)
    model.model_fields["value"].annotation = str
    model.model_rebuild(force=True)

    with pytest.raises(PlanExecutionError):
        registry.resolve("model:test:v1")


def test_fail_disposition_does_not_return_partial_success() -> None:
    plan = _plan({"verb": "null_policy", "columns": ["value"], "action": "reject"})
    with pytest.raises(InvalidRowsError) as raised:
        CleanPipeline(
            plan,
            model_registry=_registry(_row_model("NullRow", value=int)),
        ).run(pa.table({"value": [1, None]}))
    assert raised.value.row_count == 1


def test_dedupe_requires_explicit_keys_and_preserves_first_input_row() -> None:
    plan = _plan({"verb": "dedupe", "keys": ["key"]})
    result = CleanPipeline(
        plan,
        model_registry=_registry(_row_model("DedupeRow", key=int, value=str)),
    ).run(
        pa.table(
            {"key": [2, 1, 2, 1], "value": ["first-2", "first-1", "later-2", "later-1"]}
        )
    )
    assert result.table.to_pydict() == {
        "key": [2, 1],
        "value": ["first-2", "first-1"],
    }
    assert result.evidence.rows_out == 2
    assert result.evidence.dropped_rows == 2
    assert result.evidence.quarantined_rows == 0
    assert result.evidence.checkpoint_eligible
    assert [item.row_index for item in result.evidence.row_outcomes] == [0, 1, 2, 3]
    assert [item.status for item in result.evidence.row_outcomes] == [
        "accepted",
        "accepted",
        "dropped",
        "dropped",
    ]
    assert [item.reason_code for item in result.evidence.row_outcomes] == [
        "accepted",
        "accepted",
        "deduplicated",
        "deduplicated",
    ]


def test_paged_evidence_preserves_global_dedupe_and_refuses_partial_failure() -> None:
    profile = {"max_rows": 10, "max_columns": 4, "max_steps": 4, "max_outcome_rows": 2}
    plan = _plan({"verb": "dedupe", "keys": ["key"]}, profile=profile)
    pipeline = CleanPipeline(
        plan, model_registry=_registry(_row_model("PagedRow", key=int))
    )
    table = pa.table({"key": [1, 2, 1, 3, 2]})
    result = pipeline.run_paged(table)
    assert isinstance(result, PagedPrepResult)
    assert "pyarrow.Table" not in repr(result)
    pages = list(result.iter_evidence_pages())
    assert [len(page) for page in pages] == [2, 2, 1]
    outcomes = [item for page in pages for item in page]
    assert [item.row_index for item in outcomes] == [0, 1, 2, 3, 4]
    assert [item.status for item in outcomes] == [
        "accepted",
        "accepted",
        "dropped",
        "accepted",
        "dropped",
    ]
    assert result.table.to_pydict() == {"key": [1, 2, 3]}
    with pytest.raises(ProfileLimitError):
        pipeline.run(table)
    with pytest.raises(InvalidRowsError):
        pipeline.run_paged(pa.table({"key": [1, None, 2]}))


def test_paged_quarantine_evidence_matches_existing_result() -> None:
    plan = _plan(
        {"verb": "null_policy", "columns": ["key"], "action": "reject"},
        invalid_row_disposition="quarantine",
    )
    pipeline = CleanPipeline(
        plan, model_registry=_registry(_row_model("QuarantineRow", key=int))
    )
    table = pa.table({"key": [1, None, 2]})
    ordinary = pipeline.run(table)
    paged = pipeline.run_paged(table)
    assert [
        item for page in paged.iter_evidence_pages() for item in page
    ] == ordinary.evidence.row_outcomes
    assert paged.quarantined_rows == ordinary.evidence.quarantined_rows == 1
    assert paged.content_checkpoint_eligible is False


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.6")
def test_million_row_plan_produces_bounded_paged_evidence(record_property) -> None:
    plan = _plan(
        {"verb": "dedupe", "keys": ["key"]},
        profile={
            "max_rows": 1_000_000,
            "max_columns": 2,
            "max_steps": 1,
            "max_outcome_rows": 200_000,
        },
    )
    pipeline = CleanPipeline(
        plan, model_registry=_registry(_row_model("MillionRow", key=int))
    )
    table = pa.table({"key": pa.array(range(1_000_000), type=pa.int64())})
    started = time.perf_counter()
    result = pipeline.run_paged(table)
    count = 0
    for page in result.iter_evidence_pages():
        assert len(page) <= 200_000
        assert page[0].row_index == count
        count += len(page)
    record_property("elapsed_seconds", time.perf_counter() - started)
    record_property("peak_rss_kib", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    assert count == result.rows_in == result.rows_out == 1_000_000


def test_dedupe_treats_null_keys_deterministically() -> None:
    plan = _plan({"verb": "dedupe", "keys": ["key"]})
    result = CleanPipeline(
        plan,
        model_registry=_registry(_row_model("NullKeyRow", key=int | None, value=str)),
    ).run(
        pa.table(
            {
                "key": pa.array([None, None, 1], type=pa.int64()),
                "value": ["first-null", "later-null", "one"],
            }
        )
    )
    assert result.table.to_pydict() == {
        "key": [None, 1],
        "value": ["first-null", "one"],
    }


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.2")
def test_replay_is_deterministic_and_plan_is_not_mutated() -> None:
    plan = _plan(
        {"verb": "canonical_names"},
        {"verb": "dedupe", "keys": ["id"]},
        {"verb": "fill_nulls", "fills": {"name": "unknown"}},
    )
    before = plan.model_dump(mode="json")
    table = pa.table({"id": [2, 1, 2], "name": ["b", None, "later"]})
    model = _registry(_row_model("ReplayRow", id=int, name=str | None))
    first = CleanPipeline(plan, model_registry=model).run(table)
    second = CleanPipeline(plan, model_registry=model).run(table)

    assert first.table.equals(second.table)
    assert first.evidence.model_dump() == second.evidence.model_dump()
    assert plan.model_dump(mode="json") == before


def test_plan_digest_is_stable_for_fill_map_order() -> None:
    first = _plan({"verb": "fill_nulls", "fills": {"a": 1, "b": 2}})
    second = _plan({"verb": "fill_nulls", "fills": {"b": 10, "a": 9}})
    table = pa.table(
        {
            "a": pa.array([None], type=pa.int64()),
            "b": pa.array([None], type=pa.int64()),
        }
    )
    assert (
        CleanPipeline(
            first,
            model_registry=_registry(
                _row_model("DigestRowA", a=int | None, b=int | None)
            ),
        )
        .run(table)
        .evidence.plan_digest
        == CleanPipeline(
            second,
            model_registry=_registry(
                _row_model("DigestRowB", a=int | None, b=int | None)
            ),
        )
        .run(table)
        .evidence.plan_digest
    )


def test_profile_summary_contains_only_counts_and_digests() -> None:
    summary = CleanPipeline(
        _plan(),
        model_registry=_registry(_row_model("ProfileEmailRow", email=str | None)),
    ).profile(pa.table({"email": ["secret@example.test", None]}))
    dumped = json.dumps(summary.model_dump(), sort_keys=True)
    assert "secret@example.test" not in dumped
    assert "email" not in dumped
    assert summary.rows == 2
    assert summary.null_cells == 1
    assert summary.column_profiles[0].dtype == "string"
    assert summary.column_profiles[0].null_count == 1
    assert summary.column_profiles[0].null_rate == 0.5
    assert summary.column_profiles[0].distinct_count == 1
    assert "high_null_rate" in summary.column_profiles[0].warning_codes


def test_small_secret_has_no_unkeyed_content_or_field_name_fingerprint() -> None:
    # The probe column is deliberately NOT named "value": `ColumnProfile` has
    # its own generic `min_value`/`max_value` fields, so a column literally
    # named "value" collides with that unrelated schema vocabulary and makes
    # the substring assertion below fail on a false positive, not a real leak.
    plan = _plan(
        {"verb": "fill_nulls", "fills": {"secret_col": "one-row-secret"}},
    )
    pipeline = CleanPipeline(
        plan,
        model_registry=_registry(_row_model("SecretRow", secret_col=str)),
    )
    table = pa.table({"secret_col": pa.array([None], type=pa.string())})
    profile_dump = json.dumps(pipeline.profile(table).model_dump(), sort_keys=True)
    evidence_dump = json.dumps(
        pipeline.run(table).evidence.model_dump(), sort_keys=True
    )

    for dumped in (profile_dump, evidence_dump):
        assert "one-row-secret" not in dumped
        assert "secret_col" not in dumped
        assert "input_digest" not in dumped
        assert "output_digest" not in dumped
        assert "name_digest" not in dumped


# --- typed plan surface: every step model, the result and its evidence ---

from typing import get_args  # noqa: E402

from pydantic import TypeAdapter  # noqa: E402

from scion_sdk.data_prep import (  # noqa: E402
    STEP_VERBS,
    ArrowAdapter,
    ArrowTypeName,
    CanonicalNames,
    CleanStep,
    ColumnName,
    DataPrepDependencyError,
    DataPrepError,
    Dedupe,
    Digest,
    FillNulls,
    InvalidRowDisposition,
    LocalProfile,
    NullPolicy,
    OpaqueReference,
    PrepResult,
    QuarantineOutcome,
    RegisteredRowModel,
    RowOutcome,
    SafeCast,
    ScalarValue,
    SchemaVersion,
    StepEvidence,
)
from scion_sdk.data_prep._base import ProtocolModel  # noqa: E402


def test_step_union_dispatches_every_allowlisted_verb_to_its_model() -> None:
    adapter = TypeAdapter(CleanStep)
    payloads = {
        "canonical_names": ({"verb": "canonical_names"}, CanonicalNames),
        "null_policy": (
            {"verb": "null_policy", "columns": ["a"], "action": "reject"},
            NullPolicy,
        ),
        "safe_cast": (
            {
                "verb": "safe_cast",
                "column": "a",
                "source_type": "int8",
                "target_type": "int64",
            },
            SafeCast,
        ),
        "dedupe": ({"verb": "dedupe", "keys": ["a"]}, Dedupe),
        "fill_nulls": ({"verb": "fill_nulls", "fills": {"a": 0}}, FillNulls),
    }
    assert set(payloads) == set(STEP_VERBS)
    for payload, model in payloads.values():
        step = adapter.validate_python(payload)
        assert type(step) is model
        assert isinstance(step, ProtocolModel)
    with pytest.raises(ValidationError):
        adapter.validate_python({"verb": "execute_python"})


def test_scalar_aliases_bound_what_a_plan_may_carry() -> None:
    assert "int64" in get_args(ArrowTypeName.__value__)
    assert get_args(SchemaVersion.__value__) == ("1",)
    assert set(get_args(InvalidRowDisposition.__value__)) == {"fail", "quarantine"}
    assert TypeAdapter(ScalarValue).validate_python(1.5) == 1.5
    with pytest.raises(ValidationError):
        TypeAdapter(ScalarValue).validate_python([1])
    with pytest.raises(ValidationError):
        TypeAdapter(ColumnName).validate_python("")
    with pytest.raises(ValidationError):
        TypeAdapter(OpaqueReference).validate_python("-starts-with-dash")
    with pytest.raises(ValidationError):
        TypeAdapter(Digest).validate_python("sha256:short")
    with pytest.raises(ValidationError):
        LocalProfile(max_rows=0, max_columns=1, max_steps=1)


def test_typed_plan_runs_and_evidence_accounts_for_every_row() -> None:
    plan = CleanPlan(
        schema_version="1",
        steps=[
            CanonicalNames(verb="canonical_names"),
            FillNulls(verb="fill_nulls", fills={"value": 0}),
            Dedupe(verb="dedupe", keys=["key"]),
            SafeCast(
                verb="safe_cast",
                column="value",
                source_type="int8",
                target_type="int64",
            ),
        ],
        profile=LocalProfile(max_rows=10, max_columns=4, max_steps=8),
        invalid_row_disposition="fail",
        plan_ref="plan:typed",
        policy_ref="policy:typed",
        model_ref="model:test:v1",
    )
    table = ArrowAdapter.from_batches(
        [
            pa.record_batch(
                {
                    "Key": ["a", "a", "b"],
                    "Value": pa.array([1, 1, None], type=pa.int8()),
                }
            )
        ],
        profile=plan.profile,
    )
    registry = _registry(_row_model("TypedRow", key=str, value=int))
    entry = registry.resolve("model:test:v1")
    assert isinstance(entry, RegisteredRowModel)
    assert entry.digest == row_model_digest(entry.model)
    result = CleanPipeline(plan, model_registry=registry).run(table)
    assert isinstance(result, PrepResult)
    assert result.table.column_names == ["key", "value"]
    assert result.table.column("value").to_pylist() == [1, 0]
    evidence = result.evidence
    assert (evidence.rows_in, evidence.rows_out, evidence.dropped_rows) == (3, 2, 1)
    assert all(isinstance(step, StepEvidence) for step in evidence.steps)
    assert [step.verb for step in evidence.steps] == [
        "canonical_names",
        "fill_nulls",
        "dedupe",
        "safe_cast",
    ]
    assert [o.status for o in evidence.row_outcomes] == [
        "accepted",
        "dropped",
        "accepted",
    ]
    assert evidence.quarantine == []
    with pytest.raises(TypeError, match=r"pyarrow\.Table"):
        ArrowAdapter.as_table([{"key": "a"}])


def test_outcome_models_reject_inconsistent_reasons() -> None:
    assert RowOutcome(row_index=0, status="dropped", reason_code="deduplicated")
    with pytest.raises(ValidationError):
        RowOutcome(row_index=0, status="accepted", reason_code="null_rejected")
    assert QuarantineOutcome(reason_code="null_rejected", row_count=1).row_count == 1
    with pytest.raises(ValidationError):
        QuarantineOutcome(reason_code="null_rejected", row_count=0)
    assert issubclass(DataPrepDependencyError, DataPrepError)
    assert issubclass(PlanExecutionError, DataPrepError)


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.7")
def test_public_plan_view_cannot_mutate_execution() -> None:
    plan = _plan({"verb": "dedupe", "keys": ["value"]})
    pipeline = CleanPipeline(
        plan, model_registry=_registry(_row_model("IsolatedRow", value=int))
    )
    table = pa.table({"value": [1, 1, 2]})
    before = pipeline.run(table)
    exposed = pipeline.plan
    exposed.steps.clear()
    assert len(pipeline.plan.steps) == 1
    after = pipeline.run(table)
    paged = pipeline.run_paged(table)
    assert (
        after.table.to_pylist()
        == before.table.to_pylist()
        == [{"value": 1}, {"value": 2}]
    )
    assert (
        after.evidence.plan_digest == before.evidence.plan_digest == paged.plan_digest
    )
    assert paged.rows_out == 2
    assert paged.dropped_rows == 1


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.8")
def test_duplicate_schema_fields_are_rejected() -> None:
    table = pa.Table.from_arrays(
        [pa.array(["not an integer"]), pa.array([7])], names=["value", "value"]
    )
    plan = _plan({"verb": "null_policy", "columns": ["value"], "action": "allow"})
    pipeline = CleanPipeline(
        plan, model_registry=_registry(_row_model("UniqueFieldsRow", value=int))
    )
    with pytest.raises(PlanExecutionError, match="field names must be unique"):
        pipeline.run(table)
    with pytest.raises(PlanExecutionError, match="field names must be unique"):
        pipeline.run_paged(table)


@pytest.mark.spec("SCION-SOURCE-INGEST-R803.13")
def test_missing_arrow_names_the_declared_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    original_import = builtins.__import__

    def missing_arrow(name: str, *args: object, **kwargs: object) -> object:
        if name == "pyarrow":
            raise ImportError("unavailable")
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", missing_arrow)
        with pytest.raises(DataPrepDependencyError) as error:
            ArrowAdapter.as_table(object())
    assert "scion-sdk[dataprep]" in str(error.value)
