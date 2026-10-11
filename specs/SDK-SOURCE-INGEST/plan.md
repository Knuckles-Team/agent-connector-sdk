# Implementation design: source sync

1. Define normalized stream/manifest identity and checkpoint invariants in existing manifest and runner types. Keep generated `SourceCheckpoint` as the sole cursor type.
2. Add deterministic drift classification before the sink call and a typed quarantine report. Separate pure classification from I/O so adversarial fixtures run offline.
3. Route every accepted page and deletion reconciliation through generated SourceIngest operations with idempotent retries. Treat uncertain replies as a checkpoint read, not an automatic advance.
4. Port representative enterprise, document/session/feed, and vendor enrichment adapters in small slices using existing SDK ports and presets. Preserve provider license, paging, and rate limits in vendor adapters.
5. Add candidate-repair handoff as a proposal only. Activate only after graph-owned validation, shadow ingest, explicit approval, and restart proof.

Each change carries focused unit/contract tests. A final opt-in integration job runs against a provisioned graph instance and reports exact receipts.

## Ingest worker (SDK-SOURCE-INGEST-R010, R011)

The worker is a thin loop: ask the engine for admission, lane floors and routing, claim, execute with the existing source-effect runners, ack, commit. It owns no scheduling policy, so a change of lane or priority is an engine change only. The command refuses to start when the engine lacks the task-queue methods.
