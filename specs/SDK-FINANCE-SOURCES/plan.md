# Implementation design: finance sources

1. Define shared normalized source-record/provenance model at the SDK adapter boundary and keep generated graph DTOs at the sink. Document explicit interval/session/adjustment semantics.
2. Build stock history/quote/stream fixture adapter with bounded complete pagination, corporate actions, news/calendar metadata and licensing checks.
3. Add macro/vintage, FX, spot/futures, and dated real-estate adapters by extending the same SourceAdapter and manifest presets.
4. Add account read and CSV mapping-preview/import with stable activity IDs and replay-safe checkpointing.
5. Run offline conformance first; then opt-in licensed live probes and graph receipt qualification. Release each adapter independently once its own evidence is complete.

## Payment amount validation

For SDK-FINANCE-SOURCES-R900.4, the guard refuses negative or non-finite
amounts and budget limits. Spend recording rejects invalid or overflowing
amounts before changing counters. Zero spend remains valid.

## Confirmed payment binding (R900.8)

The payment client records a confirmed payment only when the supplied proof
matches the challenge and the configured wallet. A mismatch changes no spend
counter or history. This comparison does not establish the transaction on chain.
