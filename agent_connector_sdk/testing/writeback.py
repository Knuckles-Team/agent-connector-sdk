"""Conformance kit and fixtures for D18 source write-back ports."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from epistemic_graph.generated.write_back import (
    SourceChangeSet,
    WriteBackAuthorizationDecision,
    WriteBackAuthorizationMode,
    WriteBackEffectStatus,
)

from agent_connector_sdk.ports.writeback import WriteBackPort
from agent_connector_sdk.testing.results import ConformanceResult
from agent_connector_sdk.writeback.authorization import (
    DeterministicAuthorizationVerifier,
)
from agent_connector_sdk.writeback.errors import (
    AuthorizationDeniedError,
    ReconciliationRequiredError,
    SourceVersionConflictError,
)
from agent_connector_sdk.writeback.memory import (
    FixtureUncertainty,
    InMemoryWriteBackTransport,
)
from agent_connector_sdk.writeback.service import GovernedWriteBack

__all__ = [
    "WriteBackFixture",
    "WriteBackFixtureFactory",
    "make_writeback_fixture",
    "run_writeback_suite",
]


@dataclass(frozen=True)
class WriteBackFixture:
    """A fresh port plus observable fixture controls for the TCK."""

    port: WriteBackPort
    unauthorized_port: WriteBackPort
    transport: InMemoryWriteBackTransport
    change_set: SourceChangeSet


WriteBackFixtureFactory = Callable[[], WriteBackFixture]


def make_writeback_fixture() -> WriteBackFixture:
    """Build the reference deterministic write-back fixture."""
    digest = "1" * 64
    authorization = WriteBackAuthorizationDecision(
        mode=WriteBackAuthorizationMode.PROPOSAL_APPROVAL,
        authorization_ref="approval:1",
        decision_digest="2" * 64,
        input_digest="3" * 64,
        output_digest="4" * 64,
        authorized=True,
    )
    change = SourceChangeSet(
        schema_version=1,
        change_set_id="change-1",
        change_set_digest="0" * 64,
        tenant_id="tenant-1",
        actor="principal:fixture",
        purpose="fixture write-back conformance",
        connector_id="fixture-connector",
        source_instance_id="fixture-source",
        entity_id="ticket-1",
        base_source_version="v1",
        desired_patch={"status": "approved"},
        field_scope=["status"],
        source_of_truth_rule="source_accepts_approved_status",
        field_provenance={"status": "fixture:status"},
        required_capability="ticket.write",
        policy_digest=digest,
        authorization=authorization,
        idempotency_key="write:1",
        expires_at_ms=time.time_ns() // 1_000_000 + 3_600_000,
        reconciliation_procedure="lookup by idempotency key then read ticket",
    )
    change = change.model_copy(update={"change_set_digest": change.canonical_digest()})
    transport = InMemoryWriteBackTransport()
    transport.seed(change.entity_id, "v1", {"status": "new"})
    verifier = DeterministicAuthorizationVerifier()
    verifier.grant(change)
    return WriteBackFixture(
        port=GovernedWriteBack(transport, verifier),
        unauthorized_port=GovernedWriteBack(
            transport, DeterministicAuthorizationVerifier()
        ),
        transport=transport,
        change_set=change,
    )


async def _check_dry_run(factory: WriteBackFixtureFactory) -> ConformanceResult:
    fixture = factory()
    before = await fixture.port.current_version(fixture.change_set)
    preview = await fixture.port.dry_run(fixture.change_set)
    after = await fixture.port.current_version(fixture.change_set)
    passed = before == after and preview.changed_fields == ("status",)
    return ConformanceResult(
        "writeback-dry-run", passed, "dry-run mutated or misdiffed"
    )


async def _check_conflict(factory: WriteBackFixtureFactory) -> ConformanceResult:
    fixture = factory()
    fixture.transport.seed(fixture.change_set.entity_id, "v2", {"status": "new"})
    try:
        await fixture.port.apply(fixture.change_set)
    except SourceVersionConflictError:
        return ConformanceResult(
            "writeback-pre-mutation-conflict", fixture.transport.attempts == 0
        )
    return ConformanceResult("writeback-pre-mutation-conflict", False, "not refused")


async def _check_authorization(factory: WriteBackFixtureFactory) -> ConformanceResult:
    fixture = factory()
    try:
        await fixture.unauthorized_port.apply(fixture.change_set)
    except AuthorizationDeniedError:
        return ConformanceResult(
            "writeback-authorization", fixture.transport.attempts == 0
        )
    return ConformanceResult(
        "writeback-authorization", False, "unverified write applied"
    )


async def _check_idempotency(factory: WriteBackFixtureFactory) -> ConformanceResult:
    fixture = factory()
    first = await fixture.port.apply(fixture.change_set)
    second = await fixture.port.apply(fixture.change_set)
    passed = (
        first.effect_status is WriteBackEffectStatus.APPLIED
        and first == second
        and fixture.transport.attempts == 1
    )
    return ConformanceResult("writeback-idempotency", passed, "effect repeated")


async def _check_uncertain(factory: WriteBackFixtureFactory) -> ConformanceResult:
    fixture = factory()
    fixture.transport.inject_uncertainty(
        fixture.change_set.idempotency_key, FixtureUncertainty.AFTER_EFFECT
    )
    uncertain = await fixture.port.apply(fixture.change_set)
    try:
        await fixture.port.apply(fixture.change_set)
    except ReconciliationRequiredError:
        reconciled = await fixture.port.reconcile(fixture.change_set)
        passed = (
            uncertain.effect_status is WriteBackEffectStatus.OUTCOME_UNCERTAIN
            and reconciled.effect_status is WriteBackEffectStatus.APPLIED
            and not reconciled.retry_allowed
        )
        return ConformanceResult("writeback-uncertain-reconciliation", passed)
    return ConformanceResult(
        "writeback-uncertain-reconciliation", False, "retry was not blocked"
    )


async def _check_no_effect_retry(factory: WriteBackFixtureFactory) -> ConformanceResult:
    fixture = factory()
    fixture.transport.inject_uncertainty(
        fixture.change_set.idempotency_key, FixtureUncertainty.BEFORE_EFFECT
    )
    await fixture.port.apply(fixture.change_set)
    reconciled = await fixture.port.reconcile(fixture.change_set)
    applied = await fixture.port.apply(fixture.change_set)
    passed = (
        reconciled.effect_status is WriteBackEffectStatus.NO_EFFECT
        and reconciled.retry_allowed
        and applied.effect_status is WriteBackEffectStatus.APPLIED
    )
    return ConformanceResult("writeback-proven-no-effect-retry", passed)


async def run_writeback_suite(
    factory: WriteBackFixtureFactory,
) -> list[ConformanceResult]:
    """Run dry-run, conflict, authorization, idempotency and uncertainty checks."""
    return [
        await _check_dry_run(factory),
        await _check_conflict(factory),
        await _check_authorization(factory),
        await _check_idempotency(factory),
        await _check_uncertain(factory),
        await _check_no_effect_retry(factory),
    ]
