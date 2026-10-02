"""FS-06: CSV preview with ambiguous mapping/currency, then idempotent import."""

from __future__ import annotations

import pytest

from agent_connector_sdk.finance.csv_import import (
    AccountContext,
    AmbiguousColumnMappingError,
    AmbiguousCurrencyError,
    ColumnMapping,
    CsvImportPreview,
    import_activities,
    preview_csv_mapping,
)

_CONTEXT = AccountContext(
    tenant_id="tenant-1",
    source_id="broker-csv",
    provider="fixture-broker",
    instrument_id="AAA",
    account_id="acct-1",
    license_tag="licensed",
)

_MAPPING = ColumnMapping(
    header_to_field={
        "Trade Date": "event_time_utc",
        "Side": "action",
        "Qty": "quantity",
        "Price": "price",
        "Fee": "fees",
        "Ccy": "currency",
        "Settle Date": "settlement_time_utc",
    }
)

_CSV = (
    b"Trade Date,Side,Qty,Price,Fee,Ccy,Settle Date\n"
    b"2026-01-02T00:00:00+00:00,buy,10,100.5,1.0,USD,2026-01-04T00:00:00+00:00\n"
    b"2026-01-03T00:00:00+00:00,sell,5,101.0,1.0,USD,2026-01-05T00:00:00+00:00\n"
)


def test_preview_reports_row_count_and_stable_file_digest() -> None:
    preview = preview_csv_mapping(_CSV, _MAPPING)
    assert isinstance(preview, CsvImportPreview)
    assert preview.row_count == 2
    assert preview.file_digest == preview_csv_mapping(_CSV, _MAPPING).file_digest


def test_preview_rejects_a_mapping_missing_a_required_field() -> None:
    incomplete = ColumnMapping(
        header_to_field={
            k: v for k, v in _MAPPING.header_to_field.items() if v != "fees"
        }
    )
    with pytest.raises(AmbiguousColumnMappingError, match="missing"):
        preview_csv_mapping(_CSV, incomplete)


def test_preview_rejects_a_mapping_naming_two_headers_for_one_field() -> None:
    duplicated = ColumnMapping(
        header_to_field={**_MAPPING.header_to_field, "Price": "quantity"}
    )
    with pytest.raises(AmbiguousColumnMappingError, match="duplicated"):
        preview_csv_mapping(_CSV, duplicated)


def test_preview_rejects_an_unrecognized_currency_code() -> None:
    bad_currency_csv = _CSV.replace(b",USD,", b",us dollars,")
    with pytest.raises(AmbiguousCurrencyError):
        preview_csv_mapping(bad_currency_csv, _MAPPING)


def test_reimporting_identical_bytes_yields_the_same_activity_identity() -> None:
    first = import_activities(_CSV, _MAPPING, _CONTEXT)
    second = import_activities(_CSV, _MAPPING, _CONTEXT)

    assert [a.source_event_id for a in first] == [a.source_event_id for a in second]
    assert [a.row_id for a in first] == [a.row_id for a in second]
    assert [a.source_file_digest for a in first] == [
        a.source_file_digest for a in second
    ]
    assert len({a.source_event_id for a in first}) == len(first) == 2


def test_a_changed_file_is_a_new_version_with_a_different_identity() -> None:
    first = import_activities(_CSV, _MAPPING, _CONTEXT)
    changed_csv = _CSV.replace(b"100.5", b"100.6")

    changed = import_activities(changed_csv, _MAPPING, _CONTEXT)

    assert first[0].source_file_digest != changed[0].source_file_digest
    assert first[0].source_event_id != changed[0].source_event_id
