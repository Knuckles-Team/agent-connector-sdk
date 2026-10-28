# Implementation design: operational feeds

1. Add a shared event-envelope validation layer using existing `SourceAdapter`, manifest, runner and generated-client sink contracts.
2. Implement RUM, security-audit and CI/CD provider adapters independently; keep vendor-specific parsing in their connector repositories.
3. Bind checkpoint/replay to durable receipts and add schema drift quarantine before submission.
4. Run offline fixtures, then opt-in contributor-owned feed and graph integration with redacted receipts.

## Rejected event page identity (R001.1)

Stage identity changes separately while validating the entire page. Merge them
only after the adapter forms a complete `RecordPage`. This guard leaves the
durable acceptance boundary open. A failed sink submission requires replay
semantics beyond the adapter-local tracker.

## Durable event identity acceptance (R001.2)

The worker must promote staged identity only after its matching durable receipt.
An adapter-local validation success is not an acceptance receipt. R001.1 does
not close this boundary.
