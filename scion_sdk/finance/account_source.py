"""Validate account-bound Alpaca source records before graph ingestion."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceRecord,
)
from pydantic import ValidationError

from scion_sdk.adapters.mcp_tool import McpToolSourceAdapter
from scion_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from scion_sdk.finance._account_rules import _currency, _identity, _position, _positions
from scion_sdk.finance._stock_fields import _number, _text
from scion_sdk.finance.account import AccountActivity
from scion_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from scion_sdk.ports.session import McpSession

__all__ = ["AccountSourceAdapter", "AccountSourceKind"]


class AccountSourceKind(StrEnum):
    """The owner source's account snapshot, position or statement activity."""

    ACCOUNT = "account"
    POSITION = "position"
    ACTIVITY = "activity"


class AccountSourceAdapter:
    """Bind owner records to an account before forwarding them to a sink.

    Provider payloads remain unchanged. Snapshot polling is not represented as a
    provider event timestamp. This adapter makes no complete-set claim.
    """

    kind = "alpaca_account_mcp"

    def __init__(
        self,
        source: McpToolSourceAdapter,
        *,
        account_kind: AccountSourceKind,
        tenant_id: str,
        account_id: str,
    ) -> None:
        if not isinstance(account_kind, AccountSourceKind) or not all(
            isinstance(value, str) and value.strip()
            for value in (tenant_id, account_id)
        ):
            raise ValueError("account source requires a kind, tenant and account")
        self._source, self._kind = source, account_kind
        self._tenant_id, self._account_id = tenant_id, account_id

    def describe(self) -> CapabilityDescriptor:
        return self._source.describe().model_copy(update={"kind": self.kind})

    async def discover(self, session: McpSession) -> StreamDescriptor:
        return await self._source.discover(session)

    def _validate_account(self, record: SourceRecord) -> None:
        data = record.payload
        if record.record_id != self._account_id or data.get("exchange") != "alpaca":
            raise ValueError("invalid account identity")
        _currency(_text(data, "currency"))
        for field in ("equity", "cash", "buying_power", "margin_used"):
            _number(data.get(field))
        _positions(data.get("positions"))

    def _validate_position(self, record: SourceRecord) -> None:
        data = record.payload
        _position(data)
        if record.record_id != _identity([self._account_id, data["symbol"]]):
            raise ValueError("invalid position identity")

    def _validate_activity(self, record: SourceRecord) -> None:
        activity = AccountActivity.model_validate(
            {k: v for k, v in record.payload.items() if k != "record_id"}
        )
        if (
            activity.tenant_id != self._tenant_id
            or activity.source_id != self._source.preset.name
            or activity.provider != "alpaca"
        ):
            raise ValueError("activity source identity mismatch")
        expected = hashlib.sha256(
            json.dumps(
                [
                    activity.tenant_id,
                    activity.source_id,
                    activity.provider,
                    activity.account_id,
                    activity.source_event_id,
                ],
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if record.record_id != expected:
            raise ValueError("invalid activity identity")

    def _validated(self, record: SourceRecord) -> SourceRecord:
        try:
            self._check(record)
        except (ValidationError, ValueError, TypeError, KeyError, OverflowError):
            raise MalformedSourceDataError("invalid account source record") from None
        return record

    def _check(self, record: SourceRecord) -> None:
        if record.payload.get("account_id") != self._account_id:
            raise ValueError("account identity mismatch")
        validator = {
            AccountSourceKind.ACCOUNT: self._validate_account,
            AccountSourceKind.POSITION: self._validate_position,
            AccountSourceKind.ACTIVITY: self._validate_activity,
        }[self._kind]
        validator(record)

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        page = await self._source.extract(session, checkpoint)
        if page.authoritative_live_ids is not None or page.withdrawals:
            raise SourceContractError(
                "account source cannot assert a live set or withdrawals"
            )
        records = tuple(self._validated(record) for record in page.records)
        if len({record.record_id for record in records}) != len(records):
            raise MalformedSourceDataError("duplicate account source identity")
        return page.model_copy(
            update={"records": records, "mode": SourceIngestionMode.DELTA}
        )

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        raise SourceContractError(
            "account sources do not provide complete reconciliation"
        )
