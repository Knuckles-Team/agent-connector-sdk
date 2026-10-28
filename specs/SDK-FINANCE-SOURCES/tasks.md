# Tasks: finance sources

- [x] Stock history, quote, stream, adjustment, corporate-action, profile, licensed logo, news and calendars (SDK-FINANCE-SOURCES-R002).
- [x] FRED/ALFRED vintage and FOMC calendar plus other market feed sources (SDK-FINANCE-SOURCES-R001).
  - [x] Central-bank announcement calendar (`agent_connector_sdk.finance.central_bank_calendar`): one record per published vintage of a scheduled announcement, so a reschedule is a new record, never an overwrite (SDK-FINANCE-SOURCES-R001).
  - [x] Exchange history retrieval fix and a CoinMarketCap market-data adapter (SDK-FINANCE-SOURCES-R001).
- [x] Refuse same-page calendar identity collisions (SDK-FINANCE-SOURCES-R001.3).
- [x] FX, commodity spot/futures and dated real-estate valuation adapters (SDK-FINANCE-SOURCES-R003).
- [x] Verify canonical MCP FX, commodity and real-estate source streams and their domain refusals (SDK-FINANCE-SOURCES-R003.1).
- [ ] Exercise provider-specific FX, commodity and real-estate source integrations (SDK-FINANCE-SOURCES-R003.4).
- [x] Account/position reads and idempotent CSV import with preview (SDK-FINANCE-SOURCES-R004).
- [x] Macro and liquidity panels: FRED series, ETF flows, sentiment, on-chain, each tagged with source and observation time (SDK-FINANCE-SOURCES-R005).
  - [x] FRED/ALFRED macro series preserving reporting vintage (`agent_connector_sdk.finance.fred_series`) (SDK-FINANCE-SOURCES-R005).
  - [x] ETF fund-flow panel: net flow and AUM per fund per trading day (`agent_connector_sdk.finance.etf_flows`) (SDK-FINANCE-SOURCES-R005).
  - [x] Versioned liquidity composite and heat-strip panel, sentiment data, and on-chain position data (SDK-FINANCE-SOURCES-R005).
- [ ] Attach exact merged commits, offline CI and opt-in licensed source receipts before acceptance.

## Batch D source-contract verification (2026-10-26)

The grouped Batch D suite and independent storage review verify these leaves.
Each row binds to the cited assertion through `pytest.mark.spec`.

- [x] **SDK-FINANCE-SOURCES-R900.1:** Dispatch strategy exports by platform and emit all records. (`tests/test_finance_strategy_export.py::test_exporter_dispatches_by_platform_and_exports_all`)
- [x] **SDK-FINANCE-SOURCES-R900.2:** Use the first non-empty market-data provider and retain failures as warnings. (`tests/test_finance_market_data.py::test_first_non_empty_provider_wins_and_failures_become_warnings`)
- [x] **SDK-FINANCE-SOURCES-R900.5:** Refuse malformed crypto-provider responses with a typed error. (`tests/test_finance_crypto.py::test_malformed_answers_raise_provider_request_error`)

## SDK governed finance wiring follow-up (2026-10-26)

These focused tests exercise the existing default crypto egress and finance
stream-bus imports with deterministic in-memory responses.

- [ ] **SDK-FINANCE-SOURCES-R900.3:** Prove crypto defaults call governed HTTP safety and market feeds default to the SDK stream bus. (`tests/test_finance_crypto.py::test_crypto_default_fetch_uses_governed_http_safety`; `tests/test_finance_feeds.py::test_market_feed_defaults_to_sdk_stream_bus`)

- [x] Refuse non-finite multi-asset prices and inversion overflow (SDK-FINANCE-SOURCES-R003.2).

- [x] Canonicalize FX currency codes before comparing the pair (SDK-FINANCE-SOURCES-R003.3).
- [x] Refuse invalid bar intervals before subscription (SDK-FINANCE-SOURCES-R900.9).

- [x] Require canonical FRED period and vintage dates (SDK-FINANCE-SOURCES-R001.5).

- [x] Refuse repeated FRED observation identities within a page (SDK-FINANCE-SOURCES-R001.6).

- [x] Require finite funding values and provider time (SDK-FINANCE-SOURCES-R900.11).

- [x] Fetch bounded exchange history windows across pages (SDK-FINANCE-SOURCES-R001.7).
- [x] Include the exchange client in the market extra (SDK-FINANCE-SOURCES-R001.8).
- [x] Validate calendar page shape, event identity, vintage and announcement time (SDK-FINANCE-SOURCES-R001.9).
