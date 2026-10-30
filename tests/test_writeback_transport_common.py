"""Direct coverage of the shared reference-transport and dry-run helpers."""

from __future__ import annotations

import pytest
from epistemic_graph.generated.write_back import WriteBackEffectStatus

from scion_sdk.testing.writeback import make_writeback_fixture
from scion_sdk.writeback._transport_common import (
    applied_attempt,
    check_prior_effect,
    digest,
    preview_observation,
    reconciliation_observation,
)
from scion_sdk.writeback.dry_run_binding import (
    ExpectedPreview,
    expected_preview,
    require_preview_binding,
)
from scion_sdk.writeback.errors import (
    ChangeSetValidationError,
    IdempotencyConflictError,
)
from scion_sdk.writeback.models import SourceSnapshot


def _fixture():
    fx = make_writeback_fixture()
    change_set = fx.change_set
    fields = {name: "old" for name in change_set.field_scope}
    return change_set, SourceSnapshot(source_version="v1", fields=fields)


def test_digest_is_canonical() -> None:
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


def test_preview_matches_expected_binding() -> None:
    change_set, current = _fixture()
    result = preview_observation(change_set, current)
    expected = expected_preview(change_set, current)
    assert isinstance(expected, ExpectedPreview)
    require_preview_binding(change_set, current, expected, result)


def test_preview_binding_rejects_tampered_source_version() -> None:
    change_set, current = _fixture()
    result = preview_observation(change_set, current)
    expected = expected_preview(change_set, current)
    stale = SourceSnapshot(source_version="v2", fields=current.fields)
    with pytest.raises(ChangeSetValidationError):
        require_preview_binding(change_set, stale, expected, result)


def test_expected_preview_rejects_non_finite_values() -> None:
    change_set, _current = _fixture()
    bad = SourceSnapshot(
        source_version="v1",
        fields={name: float("nan") for name in change_set.field_scope},
    )
    with pytest.raises(ChangeSetValidationError):
        expected_preview(change_set, bad)


def test_applied_attempt_and_prior_effect_binding() -> None:
    change_set, _current = _fixture()
    attempt = applied_attempt(
        change_set, pre_version="v1", post_version="v1+1", observation_digest="d" * 64
    )
    assert check_prior_effect(attempt, change_set) is attempt
    other = attempt.model_copy(update={"applied_field_digest": "0" * 64})
    with pytest.raises(IdempotencyConflictError):
        check_prior_effect(other, change_set)


def test_reconciliation_retry_only_when_no_effect() -> None:
    change_set, current = _fixture()
    none = reconciliation_observation(
        change_set, current, WriteBackEffectStatus.NO_EFFECT
    )
    applied = reconciliation_observation(
        change_set, current, WriteBackEffectStatus.APPLIED
    )
    assert none.retry_allowed is True
    assert applied.retry_allowed is False
