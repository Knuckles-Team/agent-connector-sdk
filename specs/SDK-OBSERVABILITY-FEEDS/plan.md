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

## Event identity receipt boundary (R001.2)

The worker promotes staged identity only after validating the matching sink receipt.
An adapter-local validation success is not an acceptance receipt. A failed or
cancelled submission discards the stage. Concurrent use of the same adapter
refuses while a page remains unfinished.

## Durable event receipt proof (R001.3)

A graph-backed restart test must establish persistence and logical replay.
The in-memory receipt fixture proves control flow only.

## Event adapter registration (R001.4)

The SDK distribution exposes the three feed bindings through source-adapter
entry points. Loading each binding requires an activation policy. The generic worker can call an adapter supplied directly. The sync command
cannot yet construct one from a declared feed kind.
Registration and certified activation remain open work.

## Exact last-page replay (R001.6)

The accepted checkpoint binds a digest of the last raw event page and its adapter identity. A fresh adapter suppresses only the same page when the resulting checkpoint is also unchanged. Different pages with the same watermark still commit. This guard has constant size. It does not store all event identities. R001.3 remains open for process restart and general replay evidence.
