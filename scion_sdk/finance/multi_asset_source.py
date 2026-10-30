"""Validate canonical multi-asset records read through an MCP source."""

from __future__ import annotations

from datetime import UTC
from enum import StrEnum
from typing import Any

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceRecord,
)
from pydantic import ValidationError

from scion_sdk.adapters.mcp_tool import McpToolSourceAdapter
from scion_sdk.adapters.mcp_tool_paging import dig_path
from scion_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from scion_sdk.finance.multi_asset import (
    CommodityPrice,
    FxRate,
    RealEstateValuation,
)
from scion_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from scion_sdk.ports.session import McpSession

__all__ = ["MultiAssetKind", "MultiAssetSourceAdapter"]


class MultiAssetKind(StrEnum):
    """Canonical record contract selected for one source stream."""

    FX = "fx"
    COMMODITY = "commodity"
    REAL_ESTATE = "real_estate"


_MODELS = {
    MultiAssetKind.FX: FxRate,
    MultiAssetKind.COMMODITY: CommodityPrice,
    MultiAssetKind.REAL_ESTATE: RealEstateValuation,
}


class MultiAssetSourceAdapter:
    """Read one canonical FX, commodity or real-estate stream through MCP.

    Providers supply normalized finance records and retain their own credentials,
    timestamps, licenses and raw-data digests. The adapter verifies the domain
    contract and tenant/source identity before a page can reach the graph sink.
    """

    kind = "multi_asset_mcp"

    def __init__(
        self,
        source: McpToolSourceAdapter,
        *,
        asset_kind: MultiAssetKind,
        tenant_id: str,
        source_id: str,
        real_estate_max_age_days: int | None = None,
    ) -> None:
        if not isinstance(asset_kind, MultiAssetKind):
            raise ValueError("a supported multi-asset kind is required")
        if not all(
            isinstance(value, str) and value.strip() for value in (tenant_id, source_id)
        ):
            raise ValueError("tenant and source identities are required")
        if asset_kind is MultiAssetKind.REAL_ESTATE:
            if (
                type(real_estate_max_age_days) is not int
                or real_estate_max_age_days < 0
            ):
                raise ValueError("real-estate source needs a nonnegative maximum age")
        elif real_estate_max_age_days is not None:
            raise ValueError("maximum age only applies to real-estate sources")
        self._source = source
        self._asset_kind = asset_kind
        self._tenant_id = tenant_id
        self._source_id = source_id
        self._max_age = real_estate_max_age_days

    def describe(self) -> CapabilityDescriptor:
        """Return the underlying MCP source capabilities with this adapter kind."""
        return self._source.describe().model_copy(update={"kind": self.kind})

    async def discover(self, session: McpSession) -> StreamDescriptor:
        """Verify the served MCP tool contract."""
        return await self._source.discover(session)

    def _validated(self, record: SourceRecord) -> SourceRecord:
        model: Any = _MODELS[self._asset_kind]
        try:
            value = model.model_validate(record.payload)
            self._check_value(value, record)
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise MalformedSourceDataError(
                "invalid multi-asset source record"
            ) from None
        return record.model_copy(
            update={"payload": value.model_dump(mode="json", exclude_none=True)}
        )

    def _check_value(self, value: Any, record: SourceRecord) -> None:
        if (
            value.tenant_id != self._tenant_id
            or value.source_id != self._source_id
            or value.source_event_id != record.record_id
        ):
            raise ValueError("source identity mismatch")
        if self._asset_kind is not MultiAssetKind.REAL_ESTATE:
            return
        if value.estimated_value is None or value.valuation_date.utcoffset() is None:
            raise ValueError("valuation time needs a timezone")
        age = (
            value.observed_at_utc.astimezone(UTC).date()
            - value.valuation_date.astimezone(UTC).date()
        ).days
        if (
            self._max_age is None
            or age < 0
            or age != value.staleness_days
            or value.stale != (age > self._max_age)
        ):
            raise ValueError("valuation freshness mismatch")

    def _is_bounded(self) -> bool:
        return bool(
            dig_path(self._source.preset.params, self._source.preset.mode_param)
            == "delta"
        )

    def _validate_bounded_page(self, page: RecordPage) -> None:
        if self._is_bounded() and (
            page.mode is not SourceIngestionMode.DELTA
            or page.withdrawals
            or page.authoritative_live_ids is not None
        ):
            raise SourceContractError("bounded multi-asset sources require delta pages")

    def _require_reconcilable(self) -> None:
        if self._is_bounded():
            raise SourceContractError(
                "bounded multi-asset sources do not support reconciliation"
            )

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        """Validate and normalize every record before returning the whole page."""
        page = await self._source.extract(session, checkpoint)
        self._validate_bounded_page(page)
        records = tuple(self._validated(record) for record in page.records)
        if len({record.record_id for record in records}) != len(records):
            raise MalformedSourceDataError("duplicate multi-asset source identity")
        return page.model_copy(update={"records": records})

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        """Compare IDs only after validating each source page."""
        self._require_reconcilable()
        await self.discover(session)
        seen: set[str] = set()
        checkpoint = None
        for _ in range(self._source.preset.max_pages):
            page = await self.extract(session, checkpoint)
            seen.update(record.record_id for record in page.records)
            if page.exhausted:
                return ReconciliationReport(
                    stream=page.checkpoint.stream,
                    missing_from_source=tuple(sorted(known_ids - seen)),
                    unknown_to_sink=tuple(sorted(seen - known_ids)),
                )
            checkpoint = page.checkpoint.model_copy(update={"watermark": None})
        raise SourceContractError("reconciliation sweep exceeded max_pages")
