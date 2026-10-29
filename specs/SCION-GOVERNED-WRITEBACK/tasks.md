# Tasks: governed write-back

- [x] Bind exact approval, contract pin and audit reservation before apply (SCION-GOVERNED-WRITEBACK-R001, SCION-CONNECTOR-CONTROL-R002, SCION-GOVERNED-WRITEBACK-R004).
- [x] Complete durable generated-type adapter and cross-process uncertain-outcome recovery (SCION-GOVERNED-WRITEBACK-R002, SCION-GOVERNED-WRITEBACK-R003).
- [ ] Port vendor enrichment write-back through SDK transport and application API (SCION-SOURCE-INGEST-R006).
- [ ] Attach merged commit, CI run, and redacted approval/apply/reconcile receipts before acceptance.
- [x] Run the generated-type adapter, durable authorization checks, a writable connector, and restart-safe reconciliation together as one coherent, tested unit in continuous integration (SCION-GOVERNED-WRITEBACK-R005).
- [ ] Implement wallet proof model and its acceptance (SCION-GOVERNED-WRITEBACK-R001.1).
- [ ] Implement wallet proof behavior and its acceptance (SCION-GOVERNED-WRITEBACK-R001.2).
- [ ] Implement wallet proof wiring and its acceptance (SCION-GOVERNED-WRITEBACK-R001.3).
- [ ] Implement wallet proof refusal and its acceptance (SCION-GOVERNED-WRITEBACK-R001.4).
- [ ] Implement wallet proof evidence and its acceptance (SCION-GOVERNED-WRITEBACK-R001.5).
- [ ] Implement wallet proof hot-path proof and its acceptance (SCION-GOVERNED-WRITEBACK-R001.6).

## Repository source-effect definition units

- [ ] Implement and prove generic approval residual (SCION-GOVERNED-WRITEBACK-R004.1); preserve the original parent acceptance.
- [ ] Implement and prove generic deterministic replay residual (SCION-GOVERNED-WRITEBACK-R004.2); preserve the original parent acceptance.
- [x] Implement and prove generic audit reservation residual (SCION-GOVERNED-WRITEBACK-R004.3); preserve the original parent acceptance.
- [ ] Implement and prove business-rule api residual (SCION-GOVERNED-WRITEBACK-R004.4); preserve the original parent acceptance.
- [ ] Implement and prove typed repository effect request (SCION-GOVERNED-WRITEBACK-R004.5); preserve the original parent acceptance.
- [ ] Implement and prove repository path and scope resolution (SCION-GOVERNED-WRITEBACK-R004.6); preserve the original parent acceptance.
- [ ] Implement and prove approval binds the complete source effect (SCION-GOVERNED-WRITEBACK-R004.7); preserve the original parent acceptance.
- [ ] Implement and prove conditional provider mutation (SCION-GOVERNED-WRITEBACK-R004.8); preserve the original parent acceptance.
- [ ] Implement and prove actual immutable effect receipt (SCION-GOVERNED-WRITEBACK-R004.9); preserve the original parent acceptance.
- [ ] Implement and prove independent revision readback (SCION-GOVERNED-WRITEBACK-R004.10); preserve the original parent acceptance.
- [ ] Implement and prove repository restart reconciliation (SCION-GOVERNED-WRITEBACK-R004.11); preserve the original parent acceptance.
- [ ] Implement and prove served repository producer composition (SCION-GOVERNED-WRITEBACK-R004.12); preserve the original parent acceptance.
- [ ] Refuse invalid reservation IDs and mismatched file-backed reservations (SCION-GOVERNED-WRITEBACK-R004.13).
- [ ] Refuse an uncertain reconciliation that claims retry is safe (SCION-GOVERNED-WRITEBACK-R004.14).

- [x] Recheck and isolate the approved change immediately before apply (SCION-GOVERNED-WRITEBACK-R004.16).
- [x] Refuse overlapping effects within one durable connector (SCION-GOVERNED-WRITEBACK-R004.17).
