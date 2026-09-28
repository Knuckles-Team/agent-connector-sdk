# Implementation design: governed write-back

1. Preserve generated graph types and the current `WriteBackPort`, `GovernedWriteBack`, `DurableWritableConnector`, transport and ledger composition.
2. Bind audit reservation and deterministic approval to the exact canonical digest and source version before mutation. Keep proposal evaluation separate.
3. Add a synthetic writable adapter with explicit prior-effect and reconciliation semantics; then migrate one real vendor adapter using its business API.
4. Exercise crash boundaries before source effect, after effect before receipt, and after receipt before response. Restart must recover from graph-owned receipts.
5. Publish redacted approval, attempt and reconciliation evidence only after the cross-process probe passes; then widen adapter support in small slices.
