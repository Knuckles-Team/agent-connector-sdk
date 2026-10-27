# Tasks: governed write-back

- [x] Bind exact approval, contract pin and audit reservation before apply (SDK-GOVERNED-WRITEBACK-R001, SDK-CONNECTOR-CONTROL-R002, SDK-GOVERNED-WRITEBACK-R004).
- [x] Complete durable generated-type adapter and cross-process uncertain-outcome recovery (SDK-GOVERNED-WRITEBACK-R002, SDK-GOVERNED-WRITEBACK-R003).
- [ ] Port vendor enrichment write-back through SDK transport and application API (SDK-SOURCE-INGEST-R006).
- [ ] Attach merged commit, CI run, and redacted approval/apply/reconcile receipts before acceptance.
- [x] Run the generated-type adapter, durable authorization checks, a writable connector, and restart-safe reconciliation together as one coherent, tested unit in continuous integration (SDK-GOVERNED-WRITEBACK-R005).
- [ ] Implement wallet proof model and its acceptance (SDK-GOVERNED-WRITEBACK-R001.1).
- [ ] Implement wallet proof behavior and its acceptance (SDK-GOVERNED-WRITEBACK-R001.2).
- [ ] Implement wallet proof wiring and its acceptance (SDK-GOVERNED-WRITEBACK-R001.3).
- [ ] Implement wallet proof refusal and its acceptance (SDK-GOVERNED-WRITEBACK-R001.4).
- [ ] Implement wallet proof evidence and its acceptance (SDK-GOVERNED-WRITEBACK-R001.5).
- [ ] Implement wallet proof hot-path proof and its acceptance (SDK-GOVERNED-WRITEBACK-R001.6).

## Repository source-effect definition units

- [ ] Implement and prove generic approval residual (SDK-GOVERNED-WRITEBACK-R004.1); preserve the original parent acceptance.
- [ ] Implement and prove generic deterministic replay residual (SDK-GOVERNED-WRITEBACK-R004.2); preserve the original parent acceptance.
- [x] Implement and prove generic audit reservation residual (SDK-GOVERNED-WRITEBACK-R004.3); preserve the original parent acceptance.
- [ ] Implement and prove business-rule api residual (SDK-GOVERNED-WRITEBACK-R004.4); preserve the original parent acceptance.
- [ ] Implement and prove typed repository effect request (SDK-GOVERNED-WRITEBACK-R004.5); preserve the original parent acceptance.
- [ ] Implement and prove repository path and scope resolution (SDK-GOVERNED-WRITEBACK-R004.6); preserve the original parent acceptance.
- [ ] Implement and prove approval binds the complete source effect (SDK-GOVERNED-WRITEBACK-R004.7); preserve the original parent acceptance.
- [ ] Implement and prove conditional provider mutation (SDK-GOVERNED-WRITEBACK-R004.8); preserve the original parent acceptance.
- [ ] Implement and prove actual immutable effect receipt (SDK-GOVERNED-WRITEBACK-R004.9); preserve the original parent acceptance.
- [ ] Implement and prove independent revision readback (SDK-GOVERNED-WRITEBACK-R004.10); preserve the original parent acceptance.
- [ ] Implement and prove repository restart reconciliation (SDK-GOVERNED-WRITEBACK-R004.11); preserve the original parent acceptance.
- [ ] Implement and prove served repository producer composition (SDK-GOVERNED-WRITEBACK-R004.12); preserve the original parent acceptance.
- [ ] Refuse invalid reservation IDs and mismatched file-backed reservations (SDK-GOVERNED-WRITEBACK-R004.13).
- [ ] Refuse an uncertain reconciliation that claims retry is safe (SDK-GOVERNED-WRITEBACK-R004.14).
