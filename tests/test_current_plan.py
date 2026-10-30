"""Current-plan boundary validation without a runtime or server."""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from scion_sdk.current_plan import (
    CurrentPlanRead,
    CurrentPlanRequest,
    CurrentPlanSnapshot,
    PlanItem,
)

pytestmark = pytest.mark.spec("SCION-CONNECTOR-CONTROL-R070")


def snapshot(**changes):
    values = dict(
        run_id="run-1",
        revision=0,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=30),
        items=(),
    )
    return CurrentPlanSnapshot(**(values | changes))


@pytest.mark.parametrize("statuses", [(), ("done", "in_progress", "pending")])
def test_round_trip_preserves_order_and_empty_availability(statuses):
    items = tuple(PlanItem(text=str(i), status=s) for i, s in enumerate(statuses))
    read = CurrentPlanRead(availability="available", snapshot=snapshot(items=items))
    assert CurrentPlanRead.model_validate_json(read.model_dump_json()) == read
    assert read.snapshot.items == items
    assert json.loads(read.model_dump_json())["snapshot"]["items"] == [
        {"text": str(i), "status": s} for i, s in enumerate(statuses)
    ]
    request = CurrentPlanRequest(run_id="run-1")
    assert CurrentPlanRequest.model_validate_json(request.model_dump_json()) == request
    unavailable = CurrentPlanRead(availability="unavailable")
    assert unavailable.model_dump() == {"availability": "unavailable", "snapshot": None}


@pytest.mark.parametrize(
    "changes",
    [
        {"run_id": ""},
        {"run_id": "x" * 513},
        {"run_id": 12},
        {"revision": -1},
        {"revision": True},
        {"revision": "1"},
        {"revision": 1.0},
        {"tenant": "other"},
        {"items": []},
        {"observed_at": datetime(2026, 1, 1)},
        {"expires_at": datetime(2026, 1, 1)},
        {"observed_at": "2026-01-01T00:00:00Z"},
        {"expires_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"expires_at": datetime(2025, 1, 1, tzinfo=UTC)},
        {"observed_at": datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))},
    ],
)
def test_invalid_snapshot_refused(changes):
    with pytest.raises(ValidationError):
        snapshot(**changes)


@pytest.mark.parametrize(
    "values",
    [
        {"run_id": "run-1", "tenant": "other"},
        {"run_id": "run-1", "principal": "other"},
        {"run_id": ""},
        {"run_id": "x" * 513},
        {"run_id": True},
    ],
)
def test_request_cannot_supply_authority_or_invalid_id(values):
    with pytest.raises(ValidationError):
        CurrentPlanRequest.model_validate(values)


@pytest.mark.parametrize(
    "values",
    [
        {"text": "", "status": "pending"},
        {"text": 1, "status": "pending"},
        {"text": "step", "status": "unknown"},
        {"text": "step", "status": "done", "extra": True},
    ],
)
def test_invalid_items_refused(values):
    with pytest.raises(ValidationError):
        PlanItem.model_validate(values)


@pytest.mark.parametrize(
    "availability,present",
    [("available", False), ("unavailable", True), ("unknown", False)],
)
def test_read_requires_matching_availability(availability, present):
    with pytest.raises(ValidationError):
        CurrentPlanRead(
            availability=availability, snapshot=snapshot() if present else None
        )


def test_nested_constructed_values_are_revalidated():
    item = PlanItem.model_construct(text="bad", status="unknown")
    with pytest.raises(ValidationError):
        snapshot(items=(item,))
    invalid = snapshot().model_copy(update={"revision": -1})
    with pytest.raises(ValidationError):
        CurrentPlanRead(availability="available", snapshot=invalid)
    with pytest.raises(ValidationError):
        CurrentPlanRead.model_validate(
            CurrentPlanRead.model_construct(availability="available", snapshot=None)
        )


def test_models_and_item_sequence_are_immutable():
    item = PlanItem(text="step", status="pending")
    read = CurrentPlanRead(availability="available", snapshot=snapshot(items=(item,)))
    for value, field, replacement in [
        (item, "text", "changed"),
        (read.snapshot, "revision", 2),
        (read, "availability", "unavailable"),
        (CurrentPlanRequest(run_id="run-1"), "run_id", "other"),
    ]:
        with pytest.raises(ValidationError):
            setattr(value, field, replacement)
    assert isinstance(read.snapshot.items, tuple)
