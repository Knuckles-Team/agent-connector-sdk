# Tasks: connector control

- [ ] Verify canonical package tuple and input/output pins across direct and entry-point discovery (SDK-CONNECTOR-CONTROL-R002, SDK-CONNECTOR-CONTROL-R003, SDK-CONNECTOR-CONTROL-R004).
- [ ] Complete generated-type pack publisher, deterministic idempotency, and published-wheel release lock (SDK-CONNECTOR-CONTROL-R001, SDK-QUALITY-RELEASE-R001, SDK-CONNECTOR-CONTROL-R005, SDK-SOURCE-INGEST-R001).
- [ ] Add annotation and proposal-only contracts to synthetic fixture (SDK-CONNECTOR-CONTROL-R006, SDK-CONNECTOR-CONTROL-R007, SDK-CONNECTOR-CONTROL-R008).
- [ ] Migrate connector packages in five independent alphabetical batches (SDK-CONNECTOR-CONTROL-R009–SDK-CONNECTOR-CONTROL-R013).
- [ ] Retire duplicate toolkit/certification/config paths only after consumer import scans (SDK-CONNECTOR-CONTROL-R014, SDK-CONNECTOR-CONTROL-R015, SDK-CONNECTOR-CONTROL-R016).
- [ ] Attach exact merged commit, artifact digest, CI result, typed SQL receipt and live redacted pack receipt; mark accepted only when CC-01–CC-10 pass.
- [ ] Verify every connector uses the shared TLS profile with no bare verify-bypass, and that the full test suite, strict type check and docs build pass cleanly from a fresh checkout (SDK-CONNECTOR-CONTROL-R017, SDK-CONNECTOR-CONTROL-R018).
- [x] Delete `mcp/tool_mode.py` and the retired verbose 1:1 tool-surface modules; make `register_tool_surface` always register the condensed, gated tool surface with no `MCP_TOOL_MODE` branch (SDK-CONNECTOR-CONTROL-R019).
