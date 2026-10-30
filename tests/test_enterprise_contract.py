"""Interchange models retain exact units and engine-owned write-back evidence."""

from datetime import UTC, datetime

import pytest
from epistemic_graph.generated.write_back import (
    WriteBackAttemptKind,
    WriteBackEffectStatus,
    WriteBackOutcome,
    WriteBackReceipt,
)
from pydantic import ValidationError
from test_writeback_process_restart import _reference_change_set

from scion_sdk.vendor_extractors.enterprise_contract import (
    AccountRecord,
    CapabilityOperation,
    CreateInvoice,
    EnterpriseCapability,
    EnterpriseOperation,
    EnterpriseResult,
    InvoiceRecord,
    ListAccounts,
    ReadInvoice,
)


def _base() -> dict[str, str]:
    return {
        "request_id": "request-1",
        "tenant": "tenant-restart",
        "company_id": "company-1",
        "contract_revision": "v1",
        "authority": "principal:service",
    }


def _receipt() -> WriteBackReceipt:
    change = _reference_change_set()
    return WriteBackReceipt(
        actor=change.actor,
        authorization=change.authorization,
        policy_digest=change.policy_digest,
        schema_version=1,
        receipt_id="receipt-1",
        recorded_at_ms=1,
        sequence=1,
        change_set_id=change.change_set_id,
        change_set_digest=change.change_set_digest,
        tenant_id=change.tenant_id,
        idempotency_key=change.idempotency_key,
        applied_field_digest="1" * 64,
        connector_observation_digest="2" * 64,
        input_digest="3" * 64,
        output_digest="4" * 64,
        provenance_digest="5" * 64,
        kind=WriteBackAttemptKind.APPLY,
        outcome=WriteBackOutcome.APPLIED,
        effect_status=WriteBackEffectStatus.APPLIED,
        pre_source_version="v1",
        post_source_version="v2",
    )


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.32")
def test_request_and_capability_bind_operation_schema_and_scope() -> None:
    listing = EnterpriseOperation(**_base(), parameters=ListAccounts(limit=100))
    assert EnterpriseOperation.model_validate_json(listing.model_dump_json()) == listing
    read = EnterpriseOperation(
        **_base(), parameters=ReadInvoice(invoice_id="invoice-1")
    )
    assert read.parameters.operation == "read_invoice"
    write = EnterpriseOperation(
        **_base(), parameters=CreateInvoice(change_set=_reference_change_set())
    )
    assert write.parameters.change_set.tenant_id == write.tenant
    capability = EnterpriseCapability(
        connector="erp",
        connector_version="1",
        contract_revision="v1",
        company_ids=("company-1",),
        operations=(
            CapabilityOperation(
                operation="list_accounts",
                input_schema_sha256="a" * 64,
                output_schema_sha256="b" * 64,
            ),
        ),
    )
    assert capability.operations[0].operation == "list_accounts"
    with pytest.raises(ValidationError):
        EnterpriseOperation(
            **{**_base(), "tenant": "other"}, parameters=write.parameters
        )
    with pytest.raises(ValidationError):
        EnterpriseCapability(
            connector="erp",
            connector_version="1",
            contract_revision="v1",
            company_ids=("company-1", "company-1"),
            operations=capability.operations,
        )
    with pytest.raises(ValidationError):
        ListAccounts(limit=0)


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.32")
def test_results_preserve_units_and_distinguish_empty_from_refusal() -> None:
    common = dict(
        request_id="request-1",
        tenant="tenant-restart",
        company_id="company-1",
        connector="erp",
        contract_revision="v1",
    )
    account = AccountRecord(
        source_id="a",
        account_code="100",
        label="Cash",
        account_kind="asset",
        currency="USD",
    )
    success = EnterpriseResult(
        **common, operation="list_accounts", outcome="ok", accounts=(account,)
    )
    assert EnterpriseResult.model_validate_json(success.model_dump_json()) == success
    empty = EnterpriseResult(**common, operation="list_accounts", outcome="ok")
    refused = EnterpriseResult(
        **common,
        operation="list_accounts",
        outcome="refused",
        reason="unsupported_operation",
    )
    assert empty.accounts == () and empty.reason is None
    assert refused.reason == "unsupported_operation"
    invoice = InvoiceRecord(
        source_id="i",
        company_id="company-1",
        counterparty_id="c",
        currency="USD",
        amount_minor=10**19 + 1,
        scale=2,
        status="open",
        issued_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    result = EnterpriseResult(
        **common, operation="read_invoice", outcome="ok", invoice=invoice
    )
    assert (
        EnterpriseResult.model_validate_json(
            result.model_dump_json()
        ).invoice.amount_minor
        == 10**19 + 1
    )
    with pytest.raises(ValidationError):
        InvoiceRecord(**{**invoice.model_dump(), "amount_minor": 1.25})
    with pytest.raises(ValidationError):
        EnterpriseResult(
            **common,
            operation="list_accounts",
            outcome="ok",
            reason="unsupported_operation",
        )
    with pytest.raises(ValidationError):
        EnterpriseResult(
            **common,
            operation="read_invoice",
            outcome="ok",
            invoice=invoice.model_copy(update={"company_id": "wrong"}),
        )


@pytest.mark.spec("SCION-SOURCE-INGEST-R006.32")
def test_effect_requires_engine_receipt_with_matching_tenant_and_applied_status() -> (
    None
):
    common = dict(
        request_id="request-1",
        tenant="tenant-restart",
        company_id="company-1",
        connector="erp",
        contract_revision="v1",
        operation="create_invoice",
    )
    receipt = _receipt()
    result = EnterpriseResult(**common, outcome="ok", effect_receipt=receipt)
    assert result.effect_receipt == receipt
    with pytest.raises(ValidationError):
        EnterpriseResult(**common, outcome="ok")
    with pytest.raises(ValidationError):
        EnterpriseResult(
            **common,
            outcome="ok",
            effect_receipt=receipt.model_copy(
                update={"kind": WriteBackAttemptKind.DRY_RUN}
            ),
        )
    with pytest.raises(ValidationError):
        EnterpriseResult(
            **common,
            outcome="ok",
            effect_receipt=receipt.model_copy(update={"tenant_id": "other"}),
        )
    failed_receipt = receipt.model_copy(
        update={
            "effect_status": WriteBackEffectStatus.OUTCOME_UNCERTAIN,
            "outcome": WriteBackOutcome.OUTCOME_UNCERTAIN,
        }
    )
    failed = EnterpriseResult(
        **common,
        outcome="failed",
        reason="backend_failed",
        effect_receipt=failed_receipt,
    )
    assert failed.effect_receipt == failed_receipt
