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

## Durable event identity acceptance (R001.2)

Make the sink fail before acceptance. Retry the page and assert no record is
lost. Accept the receipt and verify cross-page duplicates remain idempotent.
