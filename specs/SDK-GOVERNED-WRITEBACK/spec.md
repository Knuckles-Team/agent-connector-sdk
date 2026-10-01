# Governed write-back to attached sources

**Requirement IDs:** SDK-GOVERNED-WRITEBACK-R001, SDK-GOVERNED-WRITEBACK-R002, SDK-GOVERNED-WRITEBACK-R003, SDK-GOVERNED-WRITEBACK-R004, SDK-GOVERNED-WRITEBACK-R005.
**Owner:** agent-connector-sdk source-side protocol. **Delivery state:** UNKNOWN. **Acceptance state:** OPEN.

## Outcome and boundary

A tenant can propose a scoped change to an attached source, see the exact dry-run, approve it, apply it once, and reconcile an uncertain outcome after process restart. A durable graph service owns the canonical `SourceChangeSet`, authorization and append-only `WriteBackAttempt`/reconciliation receipts. The SDK owns source-side verification and transport. A vendor adapter owns the actual app API call. If an application exposes business rules through its API, the adapter uses that API; direct database writes are not an interchangeable shortcut.

## Required protocol

The generated `SourceChangeSet` binds tenant, connector, source, change-set ID/digest, idempotency key, base source version, exact field scope, desired patch, field provenance, expiry, input/output contract digests, and authorization claim. `WriteBackPort` exposes `current_version`, `dry_run`, `apply`, and `reconcile`. `DurableWritableConnector` composes `WriteBackTransport` with a durable `WriteBackLedger` and must be reused. There is one source mutation attempt authority; no parallel connector-local approval database may replace graph receipts.

1. Register and read the exact canonical change set from the `WriteBackLedger` before every operation. Reject a missing, changed, expired, wrong-tenant, or wrong-connector record. Dry-run reads current version and returns a digest-bound preview without mutation.
2. Before apply, check optimistic source version, exact field scope and provenance, contract pin, deterministic authorization mode, approval bound to the same digest, and an audit reservation. A decision-system proposal is never approval. A denial or stale version makes zero source calls.
3. A successful application records a durable attempt and source effect identity before a caller can report completion. Repeating the same idempotency key returns the proven prior effect. Reusing the key with different digest refuses.
4. On timeout or ambiguous result, record `OUTCOME_UNCERTAIN` and stop automatic retries. After restart, replay durable receipts. Only source reconciliation proving `NO_EFFECT` permits another attempt; `APPLIED` returns the original effect and unresolved status remains closed to retry.
5. The adapter must preserve tenant and source principal isolation, redact credentials and sensitive field values from traces, and respect vendor API rate limits. A user-visible receipt contains effect status, exact target and version, approval identity/digest, and provenance digest, not raw secrets.

## Fresh-checkout development

Run `uv sync` and focused `uv run --frozen python -m pytest -q tests/test_writeback*`. Fakes implement `WriteBackTransport` and `WriteBackLedger` with controllable failures; unit and restart tests require no live app. A contributor-owned test app and graph service are used for final cross-process acceptance, with secrets supplied as references. The spec can be implemented without any private service inventory.

## Evidence and completion

| Gate | State | Evidence |
|---|---|---|
| Exact merged generated-type source implementation | OPEN | Pending commit |
| Durable restart and adversarial tests | OPEN | Pending CI run |
| Live approval/apply/reconcile receipt | OPEN | Pending redacted receipts |

**LANDED** requires exact merged source. **ACCEPTED** requires all tests below on that source, a contributor-owned writable adapter, and cross-process receipts. Current SDK write-back modules implement a source slice; they do not prove fleet or live acceptance.

Requirement IDs are defined in [requirements.md](requirements.md); delivery state per ID is in `status.json`.
