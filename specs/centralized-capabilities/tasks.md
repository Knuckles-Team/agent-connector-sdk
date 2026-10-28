# SDK-CENTRALIZED-CAPABILITIES — Implementation tasks

Governing spec: [spec.md](spec.md). Design: [plan.md](plan.md). Rows: [requirements.md](requirements.md).

- [ ] Check the module and owner row for governed http client and retry in the index test (SDK-CENTRALIZED-CAPABILITIES-R001).
- [ ] Check the module and owner row for egress guard and pinned addresses in the index test (SDK-CENTRALIZED-CAPABILITIES-R002).
- [ ] Check the module and owner row for api client base and auth strategies in the index test (SDK-CENTRALIZED-CAPABILITIES-R003).
- [ ] Check the module and owner row for pagination helpers in the index test (SDK-CENTRALIZED-CAPABILITIES-R004).
- [x] Add the same-origin `next_url` pagination mode with a loop guard and test it (SDK-CENTRALIZED-CAPABILITIES-R004).
- [ ] Check the module and owner row for rate-limit telemetry and concurrency in the index test (SDK-CENTRALIZED-CAPABILITIES-R005).
- [x] Move the shared `RateLimiter` into `httpsupport/rate_limit.py` and test it with a fake clock (SDK-CENTRALIZED-CAPABILITIES-R005).
- [ ] Check the module and owner row for error redaction and typed problems in the index test (SDK-CENTRALIZED-CAPABILITIES-R006).
- [ ] Check the module and owner row for payment challenge handling in the index test (SDK-CENTRALIZED-CAPABILITIES-R007).
- [ ] Check the module and owner row for tls profiles in the index test (SDK-CENTRALIZED-CAPABILITIES-R008).
- [ ] Check the module and owner row for credential and secret-reference resolution in the index test (SDK-CENTRALIZED-CAPABILITIES-R009).
- [ ] Check the module and owner row for selected-provider credential profile in the index test (SDK-CENTRALIZED-CAPABILITIES-R010).
- [ ] Check the module and owner row for token providers and source credentials in the index test (SDK-CENTRALIZED-CAPABILITIES-R011).
- [ ] Check the module and owner row for oidc delegation and actor identity in the index test (SDK-CENTRALIZED-CAPABILITIES-R012).
- [ ] Check the module and owner row for browser oauth with pkce in the index test (SDK-CENTRALIZED-CAPABILITIES-R013).
- [ ] Check the module and owner row for mcp server factory and served security in the index test (SDK-CENTRALIZED-CAPABILITIES-R014).
- [ ] Check the module and owner row for tool surface and tool context in the index test (SDK-CENTRALIZED-CAPABILITIES-R015).
- [ ] Check the module and owner row for graphql in the index test (SDK-CENTRALIZED-CAPABILITIES-R016).
- [ ] Check the module and owner row for a2a protocol in the index test (SDK-CENTRALIZED-CAPABILITIES-R017).
- [ ] Check the module and owner row for engine client adapter and compute in the index test (SDK-CENTRALIZED-CAPABILITIES-R018).
- [ ] Check the module and owner row for ingest bindings and source adapters in the index test (SDK-CENTRALIZED-CAPABILITIES-R019).
- [ ] Check the module and owner row for database sources in the index test (SDK-CENTRALIZED-CAPABILITIES-R020).
- [ ] Check the module and owner row for feed and document sources in the index test (SDK-CENTRALIZED-CAPABILITIES-R021).
- [ ] Check the module and owner row for message streams in the index test (SDK-CENTRALIZED-CAPABILITIES-R022).
- [ ] Check the module and owner row for market data in the index test (SDK-CENTRALIZED-CAPABILITIES-R023).
- [ ] Check the module and owner row for data preparation in the index test (SDK-CENTRALIZED-CAPABILITIES-R024).
- [ ] Check the module and owner row for embedding client in the index test (SDK-CENTRALIZED-CAPABILITIES-R025).
- [x] Add the `vector` and `vector-chroma` extras with the `db` floors and test them (SDK-CENTRALIZED-CAPABILITIES-R025).
- [ ] Check the module and owner row for vendor extractors in the index test (SDK-CENTRALIZED-CAPABILITIES-R026).
- [ ] Check the module and owner row for ontology and content packs in the index test (SDK-CENTRALIZED-CAPABILITIES-R027).
- [ ] Check the module and owner row for connector manifest and integrity in the index test (SDK-CENTRALIZED-CAPABILITIES-R028).
- [ ] Check the module and owner row for certification and fingerprints in the index test (SDK-CENTRALIZED-CAPABILITIES-R029).
- [ ] Check the module and owner row for connector identity in the index test (SDK-CENTRALIZED-CAPABILITIES-R030).
- [ ] Check the module and owner row for governed write-back in the index test (SDK-CENTRALIZED-CAPABILITIES-R031).
- [ ] Check the module and owner row for runner and cli bootstrap in the index test (SDK-CENTRALIZED-CAPABILITIES-R032).
- [ ] Check the module and owner row for health and observability in the index test (SDK-CENTRALIZED-CAPABILITIES-R033).
- [ ] Check the module and owner row for configuration, paths, and locks in the index test (SDK-CENTRALIZED-CAPABILITIES-R034).
- [ ] Check the module and owner row for privacy, entitlements, and external access in the index test (SDK-CENTRALIZED-CAPABILITIES-R035).
- [ ] Check the module and owner row for source client and repository transport in the index test (SDK-CENTRALIZED-CAPABILITIES-R036).
- [ ] Check the module and owner row for plugin entry-point groups in the index test (SDK-CENTRALIZED-CAPABILITIES-R037).
- [ ] Check the module and owner row for connector test kit in the index test (SDK-CENTRALIZED-CAPABILITIES-R038).
- [ ] Check the module and owner row for domain record models in the index test (SDK-CENTRALIZED-CAPABILITIES-R039).
- [ ] Check the module and owner row for optional dependencies come from sdk extras in the index test (SDK-CENTRALIZED-CAPABILITIES-R040).
- [x] Check that every extra is named in the extras row (SDK-CENTRALIZED-CAPABILITIES-R040).

- [ ] Refuse credential-bearing and malformed next URLs without exposing them (SDK-CENTRALIZED-CAPABILITIES-R004.1).

- [ ] Bind Link-header pagination to the initial origin (SDK-CENTRALIZED-CAPABILITIES-R004.2).

- [x] Bound Link-header parsing work (SDK-CENTRALIZED-CAPABILITIES-R004.3).
- [x] Refuse invalid tool-window page sizes (SDK-CENTRALIZED-CAPABILITIES-R004.4).
- [x] Refuse a cursor that skips a partial provider page (SDK-CENTRALIZED-CAPABILITIES-R004.5).
- [x] Stop repeated cursor and since-ID continuation tokens (SDK-CENTRALIZED-CAPABILITIES-R004.8).
- [x] Refuse overlapping pagination consumers (SDK-CENTRALIZED-CAPABILITIES-R004.7).
- [x] Refuse malformed pagination record collections (SDK-CENTRALIZED-CAPABILITIES-R004.6).
- [x] Keep upstream response problem fields out of governed public errors while retaining numeric retry timing (SDK-CENTRALIZED-CAPABILITIES-R006.1).
- [ ] Check fleet connector error paths do not expose secrets or upstream response bodies (SDK-CENTRALIZED-CAPABILITIES-R006.2).
- [x] Keep paths and query values out of governed HTTP diagnostics (SDK-CENTRALIZED-CAPABILITIES-R006.3).
