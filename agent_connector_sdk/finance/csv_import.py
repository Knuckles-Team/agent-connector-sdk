"""Column-mapping preview and idempotent CSV activity-statement import.

A column mapping must resolve every required field to exactly one CSV
header before any activity is created, and every mapped currency value must
be a recognized code. Re-importing byte-identical content always reproduces
the same ``source_event_id`` for every row, so a sink that upserts on that
identity creates no duplicate; a changed file gets a new digest and is a new
version, never silently merged with the prior import.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime

from agent_connector_sdk.finance.account import AccountActivity

__all__ = [
    "AccountContext",
    "AmbiguousColumnMappingError",
    "AmbiguousCurrencyError",
    "ColumnMapping",
    "CsvImportPreview",
    "import_activities",
    "preview_csv_mapping",
]

_REQUIRED_FIELDS = (
    "event_time_utc",
    "action",
    "quantity",
    "price",
    "fees",
    "currency",
    "settlement_time_utc",
)
_CURRENCY_CODE_LENGTH = 3


class AmbiguousColumnMappingError(ValueError):
    """A required field maps to zero or more than one CSV header."""


class AmbiguousCurrencyError(ValueError):
    """A mapped currency column holds a value that is not a 3-letter code."""


@dataclass(frozen=True)
class ColumnMapping:
    """One resolved CSV header -> canonical field name mapping."""

    header_to_field: dict[str, str]


@dataclass(frozen=True)
class CsvImportPreview:
    """The resolved mapping plus the row count it would produce, unconfirmed."""

    file_digest: str
    row_count: int
    mapping: ColumnMapping


@dataclass(frozen=True)
class AccountContext:
    """Static identity fields shared by every activity from one import."""

    tenant_id: str
    source_id: str
    provider: str
    instrument_id: str
    account_id: str
    license_tag: str


def _file_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _rows(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8"))))


def _is_currency_code(value: str) -> bool:
    return len(value) == _CURRENCY_CODE_LENGTH and value.isalpha() and value.isupper()


def _require_unambiguous_mapping(
    headers: tuple[str, ...], mapping: ColumnMapping
) -> None:
    mapped_fields = list(mapping.header_to_field.values())
    missing = [field for field in _REQUIRED_FIELDS if field not in mapped_fields]
    duplicated = sorted({f for f in mapped_fields if mapped_fields.count(f) > 1})
    unknown = [h for h in mapping.header_to_field if h not in headers]
    if missing or duplicated or unknown:
        raise AmbiguousColumnMappingError(
            f"missing={missing} duplicated={duplicated} unknown_headers={unknown}"
        )


def _require_resolved_currencies(
    rows: list[dict[str, str]], mapping: ColumnMapping
) -> None:
    currency_header = next(
        (
            header
            for header, field in mapping.header_to_field.items()
            if field == "currency"
        ),
        None,
    )
    if currency_header is None:
        return
    bad = sorted(
        {
            row[currency_header]
            for row in rows
            if not _is_currency_code(row.get(currency_header, ""))
        }
    )
    if bad:
        raise AmbiguousCurrencyError(f"unrecognized currency codes: {bad}")


def preview_csv_mapping(content: bytes, mapping: ColumnMapping) -> CsvImportPreview:
    """Resolve ambiguous columns and currencies before any activity is created."""
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    _require_unambiguous_mapping(tuple(reader.fieldnames or ()), mapping)
    rows = _rows(content)
    _require_resolved_currencies(rows, mapping)
    return CsvImportPreview(
        file_digest=_file_digest(content), row_count=len(rows), mapping=mapping
    )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _activity_from_row(
    row: dict[str, str],
    *,
    mapping: ColumnMapping,
    row_index: int,
    file_digest: str,
    context: AccountContext,
) -> AccountActivity:
    fields = {field: row[header] for header, field in mapping.header_to_field.items()}
    return AccountActivity(
        tenant_id=context.tenant_id,
        source_id=context.source_id,
        provider=context.provider,
        instrument_id=context.instrument_id,
        source_event_id=f"{file_digest}:{row_index}",
        event_time_utc=_parse_utc(fields["event_time_utc"]),
        observed_at_utc=datetime.now(UTC),
        license_tag=context.license_tag,
        source_digest=file_digest,
        account_id=context.account_id,
        source_file_digest=file_digest,
        row_id=str(row_index),
        action=fields["action"],
        quantity=float(fields["quantity"]),
        price=float(fields["price"]),
        fees=float(fields["fees"]),
        currency=fields["currency"],
        settlement_time_utc=_parse_utc(fields["settlement_time_utc"]),
    )


def import_activities(
    content: bytes, mapping: ColumnMapping, context: AccountContext
) -> tuple[AccountActivity, ...]:
    """Import every row once; re-importing identical bytes is idempotent."""
    preview = preview_csv_mapping(content, mapping)
    return tuple(
        _activity_from_row(
            row,
            mapping=mapping,
            row_index=index,
            file_digest=preview.file_digest,
            context=context,
        )
        for index, row in enumerate(_rows(content))
    )
