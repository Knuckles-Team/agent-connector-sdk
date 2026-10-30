"""Banking messages: ISO 20022 payment messages carry bounded unique identifiers."""

from __future__ import annotations

import pytest

from scion_sdk.finance.banking import (
    AMLAlertNode,
    AMLAlertSeverity,
    BankAccountNode,
    CreditRiskNode,
    ISO20022MessageFactory,
    ISO20022MessageType,
    KYCRecordNode,
    KYCRiskLevel,
    PaymentMessageNode,
    RegulatoryCapitalNode,
    SettlementCycle,
    SettlementLegNode,
)


def test_credit_transfer_is_pacs_008_with_35_character_ids() -> None:
    msg = ISO20022MessageFactory.create_credit_transfer(
        sender_bic="COBADEFFXXX",
        receiver_bic="DEUTDEFFXXX",
        amount=100000.0,
        currency="EUR",
    )
    assert msg.message_type is ISO20022MessageType.PACS_008
    assert msg.amount == pytest.approx(100000.0)
    assert msg.end_to_end_id.startswith("E2E") and len(msg.end_to_end_id) == 35
    assert msg.instruction_id.startswith("INS") and len(msg.instruction_id) == 35
    other = ISO20022MessageFactory.create_credit_transfer(
        sender_bic="COBADEFFXXX", receiver_bic="DEUTDEFFXXX", amount=1.0
    )
    assert other.end_to_end_id != msg.end_to_end_id


def test_payment_initiation_is_pain_001() -> None:
    msg = ISO20022MessageFactory.create_payment_initiation(
        sender_bic="COBADEFFXXX", amount=5.0
    )
    assert msg.message_type is ISO20022MessageType.PAIN_001


@pytest.mark.parametrize(
    ("model", "fields"),
    [
        (BankAccountNode, {"id": "a", "iban": "DE89370400440532013000"}),
        (PaymentMessageNode, {"id": "m", "message_type": "pacs.008", "amount": 5.0}),
        (KYCRecordNode, {"id": "k", "customer_id": "c", "risk_classification": "high"}),
        (AMLAlertNode, {"id": "x", "transaction_id": "t", "severity": "critical"}),
        (
            CreditRiskNode,
            {"id": "r", "account_id": "a", "probability_of_default": 0.05},
        ),
        (SettlementLegNode, {"id": "s", "payment_id": "p", "settlement_cycle": "T+2"}),
        (RegulatoryCapitalNode, {"id": "c", "cet1_ratio": 0.12}),
    ],
)
def test_records_round_trip_through_json(
    model: type, fields: dict[str, object]
) -> None:
    record = model.model_validate(fields)
    assert model.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize(
    ("enum", "value"),
    [(SettlementCycle, "bogus"), (KYCRiskLevel, "bogus"), (AMLAlertSeverity, "bogus")],
)
def test_unknown_enum_values_are_refused(enum: type, value: str) -> None:
    with pytest.raises(ValueError):
        enum(value)
