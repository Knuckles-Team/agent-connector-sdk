# Test specification: operational feeds

| ID | Fixture | Required assertion |
|---|---|---|
| OF-01 | One RUM action/error/session event | Stable identity, time basis, privacy label and payload digest. No raw token or unapproved personal data. |
| OF-02 | One audit principal/action/target event | Outcome and audit-chain reference retained; scope mismatch refuses. |
| OF-03 | One CI job with retries and deployment artifact | Run/attempt/revision/artifact identity retained. Status transition ordered, retry not conflated with first attempt. |
| OF-04 | Duplicate ID, changed digest, out-of-order page | Identical duplicate idempotent; changed digest conflict; ordering does not skip durable events. |
| OF-05 | 429, expired retention window, breaking schema | Typed lag/expiry/quarantine; no checkpoint advance or fabricated complete page. |
| OF-06 | Restart after accepted page with contributor-owned graph | Exactly-once logical replay and redacted receipt bound to tenant/source/stream/checkpoint. |

OF-01–05 run offline through focused pytest and the repository's Ruff, mypy, CCCC, KISS, Dupehound and wiring hooks. OF-06 is opt-in acceptance and records **NOT RUN** when no environment is provisioned.

## Rejected page identity isolation (R001.1)

Return a valid event followed by a malformed one. Retry the valid event on the
same adapter and assert it is emitted. This is not a durable-ingestion proof.

## Event identity receipt boundary (R001.2)

Make the sink fail before acceptance. Retry the page and assert no record is
lost. Accept the receipt and verify cross-page duplicates remain idempotent.

## Durable event receipt proof (R001.3)

Run OF-06 against a graph. Read back the receipt after restart and verify
that replay retains one logical event. The local in-memory sink is not proof.

## Event adapter registration (R001.4)

Run the sync command against a registered, certified connector. Observe the
event adapter and its feed kind through the served MCP call and sink receipt.

## Event adapter entry points (R001.5)

Discover the three feed-kind bindings. Deny activation without their exact
identity, then load and construct each binding under the SDK reference policy.
This is not a runner or durable receipt proof.

## Exact last-page replay (R001.6)

Accept a page, construct a fresh adapter, replay the identical page, then supply another event with the same timestamp. Verify the second page is accepted and the checkpoint advances. When the optional graph server binary is available, verify receipt status and exactly one graph record per event. The graph fixture uses a fresh adapter, not an operating-system process restart.

## Optional event tenant binding (R001.7)

Supply an expected tenant. Submit another tenant with an existing event ID.
Require refusal before deduplication. Verify that no sink checkpoint advances.
