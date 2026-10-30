"""SCION-CONNECTOR-CONTROL-R020.1: JSON tag-loader inventory and parity gate."""

from __future__ import annotations

import dataclasses

import pytest

from agent_connector_sdk.testing.fleet_migration import (
    JsonTagLoaderEntry,
    OperationMapping,
    loader_parity_problems,
)


def _mapping(**kw: object) -> OperationMapping:
    base = dict(
        source_operation_id="a",
        target_operation_id="a",
        source_input_schema="i",
        target_input_schema="i",
        source_output_schema="o",
        target_output_schema="o",
        source_tags=frozenset({"t"}),
        target_tags=frozenset({"t"}),
        source_authorization="read",
        target_authorization="read",
    )
    base.update(kw)
    return OperationMapping(**base)  # type: ignore[arg-type]


def _entry(*mappings: OperationMapping, registration: str = "operation"):
    return JsonTagLoaderEntry(
        "pkg",
        "abc",
        "pkg/load.py",
        "pkg/tags.json",
        "sha256:1",
        registration,
        mappings,
    )


def test_complete_matching_inventory_has_no_problems() -> None:
    assert loader_parity_problems([_entry(_mapping())], [("pkg", "pkg/load.py")]) == []


def test_uninventoried_loader_is_reported() -> None:
    problems = loader_parity_problems([_entry(_mapping())], [("pkg", "pkg/other.py")])
    assert any("not inventoried" in p for p in problems)


@pytest.mark.parametrize(
    ("change", "text"),
    [
        ({"target_input_schema": "x"}, "input schema"),
        ({"target_output_schema": "x"}, "output schema"),
        ({"target_tags": frozenset()}, "tags differ"),
        ({"target_authorization": "write"}, "authorization"),
    ],
)
def test_parity_rejects_differences(change: dict, text: str) -> None:
    problems = loader_parity_problems(
        [_entry(_mapping(**change))], [("pkg", "pkg/load.py")]
    )
    assert any(text in p for p in problems)


def test_unknown_registration_and_empty_mappings_are_rejected() -> None:
    bad = dataclasses.replace(_entry(), registration="magic")
    problems = loader_parity_problems([bad], [])
    assert any("unknown registration" in p for p in problems)
    assert any("no operation mapping" in p for p in problems)
