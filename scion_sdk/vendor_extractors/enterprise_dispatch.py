"""Authorized enterprise operations on one explicitly configured connector."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel

from scion_sdk.identity import ActorContext
from scion_sdk.ports.writeback_ledger import WriteBackLedger
from scion_sdk.vendor_extractors.enterprise_contract import (
    CapabilityOperation,
    CreateInvoice,
    EnterpriseCapability,
    EnterpriseOperation,
    EnterpriseResult,
    OperationName,
    ReadInvoice,
)
from scion_sdk.writeback.connector import DurableWritableConnector
from scion_sdk.writeback.errors import AuthorizationDeniedError


def _schema_digest(model: type[BaseModel]) -> str:
    value = json.dumps(model.model_json_schema(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def _operation_digest(request: EnterpriseOperation) -> str:
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256()
    size = 0
    for part in encoder.iterencode(request.model_dump(mode="json")):
        encoded = part.encode()
        size += len(encoded)
        if size > 1_048_576:
            raise ValueError("enterprise request exceeds the byte limit")
        digest.update(encoded)
    return digest.hexdigest()


def enterprise_schema_binding(operation: OperationName) -> CapabilityOperation:
    """The shared request and result schema identities for a declared operation."""
    return CapabilityOperation(
        operation=operation,
        input_schema_sha256=_schema_digest(EnterpriseOperation),
        output_schema_sha256=_schema_digest(EnterpriseResult),
    )


class EnterpriseAuthority(Protocol):
    """The host verifies actor, company and operation authority before a call."""

    async def authorize(
        self, actor: ActorContext, request: EnterpriseOperation
    ) -> bool: ...


class EnterpriseReader(Protocol):
    """A connector translates one approved read into the common result."""

    async def read(self, request: EnterpriseOperation) -> object: ...


@dataclass(frozen=True)
class EnterpriseWriteTarget:
    """The host-qualified connector writer and its durable receipt authority."""

    writer: DurableWritableConnector
    ledger: WriteBackLedger


class EnterpriseWriteAdmission(Protocol):
    """Admit the exact installed source operation and its transaction contract."""

    async def admit(
        self,
        actor: ActorContext,
        request: EnterpriseOperation,
        capability: EnterpriseCapability,
    ) -> EnterpriseWriteTarget | None: ...


class EnterpriseDispatcher:
    """Dispatch only to the host-configured connector; never select a substitute."""

    def __init__(
        self,
        capability: EnterpriseCapability,
        *,
        authority: EnterpriseAuthority,
        reader: EnterpriseReader,
        write_admission: EnterpriseWriteAdmission | None = None,
    ) -> None:
        self._capability = capability
        self._authority = authority
        self._reader = reader
        self._write_admission = write_admission

    def _result(
        self,
        request: EnterpriseOperation,
        reason: Literal[
            "unsupported_operation",
            "schema_mismatch",
            "unauthorized",
            "invalid_request",
            "backend_failed",
        ],
    ) -> EnterpriseResult:
        try:
            digest = _operation_digest(request)
        except (TypeError, ValueError):
            digest = None
        return EnterpriseResult(
            request_id=request.request_id,
            tenant=request.tenant,
            company_id=request.company_id,
            connector=self._capability.connector,
            contract_revision=request.contract_revision,
            operation=request.parameters.operation,
            operation_digest=digest,
            outcome="refused",
            reason=reason,
        )

    async def execute(
        self, actor: ActorContext, request: EnterpriseOperation
    ) -> EnterpriseResult:
        """Authorize exact scope and schema, then issue one read or governed effect."""
        request = EnterpriseOperation.model_validate(request.model_dump(mode="python"))
        try:
            request_digest = _operation_digest(request)
        except (TypeError, ValueError):
            return self._result(request, "invalid_request")
        if (
            not actor.authenticated
            or actor.tenant_id != request.tenant
            or actor.actor_id != request.authority
        ):
            return self._result(request, "unauthorized")
        capability = self._capability
        try:
            authorized = await self._authority.authorize(actor, request)
        except Exception:
            return self._result(request, "unauthorized")
        if not authorized:
            return self._result(request, "unauthorized")
        if _operation_digest(request) != request_digest:
            return self._result(request, "invalid_request")
        if request.company_id not in capability.company_ids:
            return self._result(request, "unauthorized")
        declared = next(
            (
                item
                for item in capability.operations
                if item.operation == request.parameters.operation
            ),
            None,
        )
        if declared is None:
            return self._result(request, "unsupported_operation")
        if (
            request.contract_revision != capability.contract_revision
            or declared != enterprise_schema_binding(declared.operation)
        ):
            return self._result(request, "schema_mismatch")
        try:
            if isinstance(request.parameters, CreateInvoice):
                return await self._write(actor, request)
            result = await self._reader.read(request)
        except AuthorizationDeniedError:
            return self._result(request, "unauthorized")
        except Exception:
            return self._result(request, "backend_failed").model_copy(
                update={"outcome": "failed"}
            )
        if not isinstance(result, EnterpriseResult):
            return self._result(request, "schema_mismatch")
        try:
            result = EnterpriseResult.model_validate(result.model_dump(mode="python"))
        except ValueError:
            return self._result(request, "schema_mismatch")
        if (
            result.request_id,
            result.tenant,
            result.company_id,
            result.connector,
            result.contract_revision,
            result.operation,
        ) != (
            request.request_id,
            request.tenant,
            request.company_id,
            capability.connector,
            request.contract_revision,
            request.parameters.operation,
        ):
            return self._result(request, "schema_mismatch")
        if (
            isinstance(request.parameters, ReadInvoice)
            and result.outcome == "ok"
            and (
                result.invoice is None
                or result.invoice.source_id != request.parameters.invoice_id
            )
        ):
            return self._result(request, "schema_mismatch")
        if result.outcome == "ok" and not result.backend_receipt:
            return self._result(request, "schema_mismatch")
        return result.model_copy(
            update={"operation_digest": _operation_digest(request)}
        )

    async def _write(
        self, actor: ActorContext, request: EnterpriseOperation
    ) -> EnterpriseResult:
        if not isinstance(request.parameters, CreateInvoice):
            return self._result(request, "invalid_request")
        change = request.parameters.change_set
        patch = change.desired_patch
        invoice = patch.get("invoice")
        if (
            change.actor != actor.actor_id
            or change.connector_id != self._capability.connector
            or patch.get("operation") != "create_invoice"
            or patch.get("company_id") != request.company_id
            or set(patch) != {"operation", "company_id", "invoice"}
            or not isinstance(invoice, dict)
            or invoice.get("company") != request.company_id
        ):
            return self._result(request, "invalid_request")
        if self._write_admission is None:
            return self._result(request, "unsupported_operation")
        admitted_digest = _operation_digest(request)
        target = await self._write_admission.admit(actor, request, self._capability)
        if target is None:
            return self._result(request, "unauthorized")
        if _operation_digest(request) != admitted_digest:
            return self._result(request, "invalid_request")
        attempt = await target.writer.apply(change)
        cursor: int | None = None
        for _ in range(100):
            page = await target.ledger.receipts(
                change.tenant_id, change.change_set_id, after_sequence=cursor
            )
            for record in reversed(page.receipts):
                receipt = getattr(record, "receipt", None)
                if (
                    receipt is not None
                    and all(
                        getattr(receipt, name) == getattr(attempt, name)
                        for name in type(attempt).model_fields
                    )
                    and (
                        receipt.actor == change.actor
                        and receipt.authorization == change.authorization
                        and receipt.policy_digest == change.policy_digest
                    )
                ):
                    outcome: Literal["ok", "failed"] = (
                        "ok" if receipt.outcome.value == "applied" else "failed"
                    )
                    return EnterpriseResult(
                        request_id=request.request_id,
                        tenant=request.tenant,
                        company_id=request.company_id,
                        connector=self._capability.connector,
                        contract_revision=request.contract_revision,
                        operation="create_invoice",
                        operation_digest=_operation_digest(request),
                        outcome=outcome,
                        reason=None if outcome == "ok" else "backend_failed",
                        effect_receipt=receipt,
                    )
            if page.next_sequence is None or (
                cursor is not None and page.next_sequence <= cursor
            ):
                break
            cursor = page.next_sequence
        raise RuntimeError("governed write receipt unavailable")
