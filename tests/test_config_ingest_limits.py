"""Connector ingestion settings have one bounded policy in the SDK."""

import pytest

from agent_connector_sdk.config import (
    validate_discovery_limit,
    validate_ingest_budget,
    validate_ingest_limit,
)


@pytest.mark.parametrize(
    ("name", "lower", "upper"),
    [
        ("ingest_max_records", 1, 10_000),
        ("ingest_page_size", 1, 1_000),
        ("ingest_max_pages", 1, 1_000),
        ("ingest_max_row_bytes", 256, 8_388_608),
        ("ingest_max_total_bytes", 256, 67_108_864),
        ("ingest_max_nesting_depth", 1, 64),
        ("ingest_max_collection_items", 1, 100_000),
    ],
)
def test_connector_ingest_limit_is_bounded(name: str, lower: int, upper: int) -> None:
    assert validate_ingest_limit(name, str(lower)) == lower
    assert validate_ingest_limit(name, upper) == upper
    for invalid in (True, False, 1.5, "1.5", lower - 1, upper + 1):
        with pytest.raises(ValueError):
            validate_ingest_limit(name, invalid)


def test_unknown_ingest_limit_is_not_accepted() -> None:
    with pytest.raises(KeyError):
        validate_ingest_limit("unregistered", 1)


@pytest.mark.parametrize(
    ("name", "upper"),
    [("discovery_max_types", 500), ("discovery_max_depth", 12)],
)
def test_connector_discovery_limit_is_bounded(name: str, upper: int) -> None:
    assert validate_discovery_limit(name, 1) == 1
    assert validate_discovery_limit(name, upper) == upper
    for invalid in (True, 1.5, "1.5", 0, upper + 1):
        with pytest.raises(ValueError):
            validate_discovery_limit(name, invalid)


def test_total_budget_covers_one_row() -> None:
    validate_ingest_budget(256, 256)
    with pytest.raises(ValueError, match="cover one bounded row"):
        validate_ingest_budget(1_024, 512)
