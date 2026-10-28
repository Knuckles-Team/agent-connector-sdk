"""Standalone readable rendering; certification and pack wiring remain separate."""

from dataclasses import FrozenInstanceError

import pytest

from agent_connector_sdk.artifacts.readable_form import (
    FittedAnalysis,
    FittedTerm,
    ReadableForm,
    default_readable_renderer,
    render_readable,
)
from agent_connector_sdk.artifacts.tool_facts import SideEffect, ToolContractFacts


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R048.2")
def test_render_is_bounded_plain_text() -> None:
    result = FittedAnalysis(
        (FittedTerm("age", "+0.5"), FittedTerm("cost", "-2")), "R2=0.8"
    )
    form = ReadableForm("default")
    assert (
        default_readable_renderer(result) == "age: +0.5\ncost: -2\nFit quality: R2=0.8"
    )
    assert render_readable(result, ReadableForm("default", max_chars=8)) == "age: +0."
    assert render_readable(result, ReadableForm("default", max_chars=0)) == ""
    assert render_readable(result, form, renderer=lambda _: "custom") == "custom"
    with pytest.raises(FrozenInstanceError):
        form.__setattr__("max_chars", 1)
    with pytest.raises(ValueError):
        ReadableForm("default", max_chars=-1)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R048.1")
def test_model_is_frozen_and_optional_on_facts() -> None:
    base = {
        "read_only": True,
        "side_effects": frozenset({SideEffect.NONE}),
        "arg_schema": {"type": "object"},
        "schema_tokens": 0,
        "declared_by": "connector",
    }
    empty = ToolContractFacts.model_validate(base)
    assert empty.readable_form is None
    form = ReadableForm("fitted", question_set_ref="questions.json", score=0.9)
    facts = ToolContractFacts.model_validate({**base, "readable_form": form})
    assert facts.readable_form == form
    assert ToolContractFacts.model_validate(facts.model_dump()) == facts
    with pytest.raises(FrozenInstanceError):
        form.__setattr__("score", 0.5)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R048.7")
@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_readable_score_refuses_non_ratios(score: float) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValueError):
        ReadableForm("default", score=score)
    base = {
        "read_only": True,
        "side_effects": {"none"},
        "arg_schema": {},
        "schema_tokens": 0,
        "declared_by": "connector",
        "readable_form": {"template_id": "default", "score": score},
    }
    with pytest.raises(ValidationError):
        ToolContractFacts.model_validate(base)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R048.7")
@pytest.mark.parametrize("score", [0.0, 0.5, 1.0])
def test_readable_score_accepts_finite_ratio(score: float) -> None:
    assert ReadableForm("default", score=score).score == score
    facts = ToolContractFacts.model_validate(
        {
            "read_only": True,
            "side_effects": {"none"},
            "arg_schema": {},
            "schema_tokens": 0,
            "declared_by": "connector",
            "readable_form": {"template_id": "default", "score": score},
        }
    )
    assert facts.readable_form is not None
    assert facts.readable_form.score == score
