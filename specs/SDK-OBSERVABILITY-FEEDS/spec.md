# Operational event feeds through the source adapter contract

**Program ID:** EH-410. **Owner:** agent-connector-sdk contract; each event connector owns provider transport. **Delivery state:** SPECIFIED. **Acceptance state:** OPEN.

## Outcome and model

Real-user monitoring (RUM), security audit, and CI/CD events can enter the same durable source pipeline as other systems of record. The SDK provides authenticated transport, bounded paging/streaming, stable event identity, manifests, checkpointing, and schema drift quarantine. It does not interpret an event as a verified incident, vulnerability, release, or user outcome; graph-side policy and analysis own those conclusions.

An event envelope carries tenant/source/stream IDs; provider event ID or canonical source digest; event kind and schema version; event time, source-observed time and ingest time; actor and target references; trace/correlation ID if supplied; visibility/sensitivity label; license/retention metadata; payload digest; and source provenance. RUM captures page/action/error/session signals without raw credential or unapproved personal data. Security audit captures principal, action, target, outcome, and audit-chain reference. CI/CD captures repository revision, job/run/attempt identity, status transitions, artifact digest and deployment environment label. Missing required identity or impossible time order is refused, not patched with current time.

`SourceAdapter.discover` checks event API schema, scopes, pagination and retention window. `extract` returns a bounded page after the graph-owned checkpoint. Webhooks may enqueue hints, but durable source reconciliation controls completion. A repeated event ID with the same digest is idempotent; same ID with changed payload is a version/conflict, not a silent overwrite. Deletions and retention expiry use explicit tombstone/expiry outcomes. Drift quarantine prevents checkpoint advance. Backpressure bounds memory, concurrency and retry; 429 and outages surface typed lag, not fabricated success.

## Portable contribution and completion

Use synthetic RUM, audit and CI event fixtures with fake sessions and generated-client ports after `uv sync`; no production telemetry, private fleet, or hosted service is necessary for source tests. **LANDED** requires exact merged adapter contract and one provider implementation per feed kind. **ACCEPTED** requires the tests below, a graph-backed receipt and restart replay. No source implementation or live evidence is claimed by this spec.
