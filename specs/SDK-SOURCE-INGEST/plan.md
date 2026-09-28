# Implementation design: source sync

1. Define normalized stream/manifest identity and checkpoint invariants in existing manifest and runner types; keep generated `SourceCheckpoint` as the sole cursor type.
2. Add deterministic drift classification before the sink call and a typed quarantine report. Separate pure classification from I/O so adversarial fixtures run offline.
3. Route every accepted page and deletion reconciliation through generated SourceIngest operations with idempotent retries. Treat uncertain replies as a checkpoint read, not an automatic advance.
4. Port representative enterprise, document/session/feed, and vendor enrichment adapters in small slices using existing SDK ports and presets. Preserve provider license, paging, and rate limits in vendor adapters.
5. Add candidate-repair handoff as a proposal only. Activate only after graph-owned validation, shadow ingest, explicit approval, and restart proof.

Each change carries focused unit/contract tests; a final opt-in integration job runs against a provisioned graph instance and reports exact receipts.
