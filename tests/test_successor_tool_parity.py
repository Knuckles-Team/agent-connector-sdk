"""Successor tool parity (SCION-CONNECTOR-CONTROL-R020.4 is partial: covered_by is not fed by the gate)."""

from __future__ import annotations

import pytest

from scion_sdk.testing.successor_parity import (
    SuccessorToolParity,
    compare_successor_tools,
)


def test_kept_split_and_covered_tools_are_accepted() -> None:
    result = compare_successor_tools(
        ["a", "router", "old"],
        ["a", "router_get", "router_put", "new_op"],
        covered_by={"old": "new_op"},
    )
    assert result.kept == ("a",)
    assert result.split == {"router": ("router_get", "router_put")}
    assert result.covered == {"old": "new_op"}
    assert result.accepted


def test_one_lost_tool_is_refused() -> None:
    result = compare_successor_tools(["a", "b"], ["a"])
    assert result.lost == ("b",)
    assert not result.accepted


def test_a_remaining_dispatch_tool_is_refused() -> None:
    result = compare_successor_tools(["r"], ["r"], dispatch_tools=["r"])
    assert result.dispatch_remaining == ("r",)
    assert not result.accepted


def test_a_cover_naming_an_unserved_tool_is_lost() -> None:
    assert compare_successor_tools(["x"], [], covered_by={"x": "y"}).lost == ("x",)


def test_duplicate_names_raise() -> None:
    assert SuccessorToolParity((), {}, {}, (), ()).accepted
    with pytest.raises(ValueError):
        compare_successor_tools(["a", "a"], ["a"])
