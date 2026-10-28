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
