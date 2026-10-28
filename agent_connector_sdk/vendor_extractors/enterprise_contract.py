"""Typed operation and result contracts for enterprise connector interchange.

These models do not authenticate callers, select a backend, or execute writes.
Effecting requests and results use epistemic-graph's generated write-back types.
"""

from __future__ import annotations

from typing import Annotated, Literal

from epistemic_graph.generated.write_back import (
    SourceChangeSet,
    WriteBackAttemptKind,
    WriteBackEffectStatus,
    WriteBackOutcome,
    WriteBackReceipt,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AccountRecord",
    "CapabilityOperation",
    "CreateInvoice",
    "EnterpriseCapability",
    "EnterpriseOperation",
    "EnterpriseResult",
    "InvoiceRecord",
    "ListAccounts",
    "ReadInvoice",
]

Identity = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^\S(?:.*\S)?$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
OperationName = Literal["list_accounts", "read_invoice", "create_invoice"]
Reason = Literal[
    "unsupported_operation",
    "schema_mismatch",
    "unauthorized",
    "invalid_request",
    "backend_failed",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AccountRecord(_Model):
    """One normalized account from the selected connector."""

    source_id: Identity
    account_code: Identity
    label: Identity
    account_kind: Identity
    currency: Currency


class InvoiceRecord(_Model):
    """One invoice with integer minor units and its declared decimal scale."""

    source_id: Identity
    company_id: Identity
    counterparty_id: Identity
    currency: Currency
    amount_minor: int
    scale: int = Field(ge=0, le=18)
    status: Identity
    issued_at: AwareDatetime


class ListAccounts(_Model):
    """Bounded account listing parameters."""

    operation: Literal["list_accounts"] = "list_accounts"
    limit: int = Field(ge=1, le=1000)
    continuation: str | None = Field(default=None, max_length=2048)


class ReadInvoice(_Model):
    """Identify one invoice without selecting a provider."""

    operation: Literal["read_invoice"] = "read_invoice"
    invoice_id: Identity


class CreateInvoice(_Model):
    """An engine-owned change set; approval is checked by write-back."""

    operation: Literal["create_invoice"] = "create_invoice"
    change_set: SourceChangeSet


Parameters = Annotated[
    ListAccounts | ReadInvoice | CreateInvoice, Field(discriminator="operation")
]


class EnterpriseOperation(_Model):
    """A request bound to tenant, company, declared authority and revision."""

    request_id: Identity
    tenant: Identity
    company_id: Identity
    contract_revision: Identity
    authority: Identity
    parameters: Parameters

    @model_validator(mode="after")
    def bind_change_set(self) -> EnterpriseOperation:
        if isinstance(self.parameters, CreateInvoice):
            change_set = self.parameters.change_set
            if change_set.tenant_id != self.tenant:
                raise ValueError("change set tenant does not match request")
        return self


class CapabilityOperation(_Model):
    """A connector's schema identities for one declared operation."""

    operation: OperationName
    input_schema_sha256: Digest
    output_schema_sha256: Digest


class EnterpriseCapability(_Model):
    """A connector's explicit company and operation scope."""

    connector: Identity
    connector_version: Identity
    contract_revision: Identity
    company_ids: tuple[Identity, ...] = Field(
        min_length=1, max_length=1000, strict=False
    )
    operations: tuple[CapabilityOperation, ...] = Field(
        min_length=1, max_length=3, strict=False
    )

    @model_validator(mode="after")
    def distinct_declarations(self) -> EnterpriseCapability:
        if len(set(self.company_ids)) != len(self.company_ids):
            raise ValueError("duplicate company scope")
        names = [item.operation for item in self.operations]
        if len(set(names)) != len(names):
            raise ValueError("duplicate operation")
        return self


class EnterpriseResult(_Model):
    """A response preserving selected connector, outcomes and effect receipts."""

    request_id: Identity
    tenant: Identity
    company_id: Identity
    connector: Identity
    contract_revision: Identity
    operation: OperationName
    operation_digest: Digest | None = None
    backend_receipt: (
        Annotated[
            str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:-]+$")
        ]
        | None
    ) = None
    outcome: Literal["ok", "refused", "failed"]
    reason: Reason | None = None
    accounts: tuple[AccountRecord, ...] = Field(
        default=(), max_length=1000, strict=False
    )
    invoice: InvoiceRecord | None = None
    effect_receipt: WriteBackReceipt | None = None
    continuation: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def coherent_result(self) -> EnterpriseResult:
        if self.outcome != "ok":
            self._validate_failure()
            return self
        if self.reason is not None:
            raise ValueError("successful result cannot have a refusal reason")
        if self.operation == "list_accounts":
            self._validate_accounts()
        elif self.operation == "read_invoice":
            self._validate_invoice()
        else:
            self._validate_effect()
        return self

    def _validate_failure(self) -> None:
        if (
            self.reason is None
            or self.accounts
            or self.invoice
            or self.continuation
            or self.backend_receipt
        ):
            raise ValueError("failure must have a reason and no data")
        if self.effect_receipt is None:
            return
        if (
            self.operation != "create_invoice"
            or self.effect_receipt.tenant_id != self.tenant
            or self.effect_receipt.kind is not WriteBackAttemptKind.APPLY
        ):
            raise ValueError("failure receipt does not bind the operation")

    def _validate_accounts(self) -> None:
        if self.invoice is not None or self.effect_receipt is not None:
            raise ValueError("account listing has incompatible result")

    def _validate_invoice(self) -> None:
        if (
            self.accounts
            or self.invoice is None
            or self.effect_receipt is not None
            or self.continuation
        ):
            raise ValueError("invoice read has incompatible result")
        if self.invoice.company_id != self.company_id:
            raise ValueError("invoice company does not match result")

    def _validate_effect(self) -> None:
        if (
            self.accounts
            or self.invoice is not None
            or self.effect_receipt is None
            or self.continuation
        ):
            raise ValueError("invoice creation requires its effect receipt")
        if (
            self.effect_receipt.tenant_id != self.tenant
            or self.effect_receipt.kind is not WriteBackAttemptKind.APPLY
            or not self.effect_receipt.authorization.authorized
            or self.effect_receipt.effect_status is not WriteBackEffectStatus.APPLIED
            or self.effect_receipt.outcome is not WriteBackOutcome.APPLIED
        ):
            raise ValueError(
                "invoice creation requires an applied receipt in this tenant"
            )
