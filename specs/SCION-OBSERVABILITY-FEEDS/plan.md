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

An isolated graph accepts a synthetic page. A second worker process replays it.
Graph status retains the same receipt, and readback has one logical event.
The graph test skips if its optional server binary is absent.

## Event adapter registration (R001.4)

The live source declaration may name a feed kind. The sync runner loads that
binding through its composition root's activation policy and pins the live tool
contract before extraction. A missing or unauthorized policy refuses the feed.
The event tenant binding remains optional; this wiring does not establish a
trusted host tenant.

## Exact last-page replay (R001.6)

The accepted checkpoint binds a digest of the last raw event page and its adapter identity. A fresh adapter suppresses only the same page when the resulting checkpoint is also unchanged. Different pages with the same watermark still commit. This guard has constant size. It does not store all event identities. R001.3 proves a restart for one exact page. It does not prove all replay cases.

## Bounded identity index (R001.8)

One adapter retains at most 100,000 identity entries and 16 MiB of UTF-8
identity and digest bytes, including a candidate page. It refuses new entries
at either bound. Known duplicates and conflicts still resolve. This limit
does not bound provider response size. Reaching it stops new events until a
separate safe reset or durable identity strategy exists.

## Optional event tenant binding (R001.7)

The host may construct an adapter with an expected tenant. Each envelope must
match it before identity deduplication. The host owns tenant authentication.
The optional parameter does not bind the served runner or an unconfigured host.
