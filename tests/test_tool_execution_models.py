"""Shape validation for execution context and progress values."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_connector_sdk.mcp.context import (
    MAX_PROGRESS_MESSAGE_BYTES,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolProgress,
)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R050.1")
def test_context_and_progress_models_validate_identity_and_bounds() -> None:
    context = {
        "tenant_id": "tenant",
        "actor_id": "actor",
        "session_id": "session",
        "request_id": "request",
        "connector_id": "connector",
        "operation_id": "op",
        "deadline": datetime.now(UTC),
        "progress_token": 12,
    }
    value = ToolExecutionContext(**context)
    assert value.progress_token == 12
    with pytest.raises(ValidationError):
        value.request_id = "other"
    for invalid in (
        {"tenant_id": " "},
        {"operation_id": ""},
        {"deadline": datetime(2026, 1, 1)},
        {"progress_token": True},
    ):
        with pytest.raises(ValidationError):
            ToolExecutionContext.model_validate({**context, **invalid})
    assert (
        ToolProgress(sequence=1, completed=1, total=2, message="é" * 2048).sequence == 1
    )
    for invalid in (
        {"completed": float("nan")},
        {"completed": float("inf")},
        {"completed": -1},
        {"total": 0.5},
        {"sequence": -1},
        {"message": "é" * (MAX_PROGRESS_MESSAGE_BYTES // 2 + 1)},
    ):
        with pytest.raises(ValidationError):
            ToolProgress.model_validate({"sequence": 1, "completed": 1, **invalid})
    assert (
        ToolExecutionResult(
            state="uncertain", last_sequence=1, effect_receipt_ref="receipt"
        ).state
        == "uncertain"
    )
    with pytest.raises(ValidationError):
        ToolExecutionResult.model_validate({"state": "unknown", "last_sequence": 0})
