# Tasks: finance sources

- [x] Stock history, quote, stream, adjustment, corporate-action, profile, generated illustration, news and calendars (SCION-FINANCE-SOURCES-R002).
- [x] FRED/ALFRED vintage and FOMC calendar plus other market feed sources (SCION-FINANCE-SOURCES-R001).
  - [x] Central-bank announcement calendar (`scion_sdk.finance.central_bank_calendar`): one record per published vintage of a scheduled announcement, so a reschedule is a new record, never an overwrite (SCION-FINANCE-SOURCES-R001).
  - [x] Exchange history retrieval fix and a CoinMarketCap market-data adapter (SCION-FINANCE-SOURCES-R001).
- [x] Refuse same-page calendar identity collisions (SCION-FINANCE-SOURCES-R001.3).
- [x] Verify exchange, CoinMarketCap, FRED vintage and FOMC announcement records through the shared source contract (SCION-FINANCE-SOURCES-R001.2).
- [x] FX, commodity spot/futures and dated real-estate valuation adapters (SCION-FINANCE-SOURCES-R003).
- [x] Verify canonical MCP FX, commodity and real-estate source streams and their domain refusals (SCION-FINANCE-SOURCES-R003.1).
- [x] Exercise provider-specific FX, commodity and real-estate source integrations (SCION-FINANCE-SOURCES-R003.4).
- [x] Account/position reads and idempotent CSV import with preview (SCION-FINANCE-SOURCES-R004).
- [x] Bind account, position and CSV sources and replay them into the graph (SCION-FINANCE-SOURCES-R004.1).
- [x] Macro and liquidity panels: FRED series, ETF flows, sentiment, on-chain, each tagged with source and observation time (SCION-FINANCE-SOURCES-R005).
  - [x] FRED/ALFRED macro series preserving reporting vintage (`scion_sdk.finance.fred_series`) (SCION-FINANCE-SOURCES-R005).
  - [x] ETF fund-flow panel: net flow and AUM per fund per trading day (`scion_sdk.finance.etf_flows`) (SCION-FINANCE-SOURCES-R005).
  - [x] Versioned liquidity composite and heat-strip panel, sentiment data, and on-chain position data (SCION-FINANCE-SOURCES-R005).
- [ ] Attach exact merged commits, offline CI and opt-in licensed source receipts before acceptance.

## Batch D source-contract verification (2026-10-26)

The grouped Batch D suite and independent storage review verify these leaves.
Each row binds to the cited assertion through `pytest.mark.spec`.

- [x] **SCION-FINANCE-SOURCES-R900.1:** Dispatch strategy exports by platform and emit all records. (`tests/test_finance_strategy_export.py::test_exporter_dispatches_by_platform_and_exports_all`)
- [x] **SCION-FINANCE-SOURCES-R900.2:** Use the first non-empty market-data provider and retain failures as warnings. (`tests/test_finance_market_data.py::test_first_non_empty_provider_wins_and_failures_become_warnings`)
- [x] **SCION-FINANCE-SOURCES-R900.5:** Refuse malformed crypto-provider responses with a typed error. (`tests/test_finance_crypto.py::test_malformed_answers_raise_provider_request_error`)

## SDK governed finance wiring follow-up (2026-10-26)

These focused tests exercise the existing default crypto egress and finance
stream-bus imports with deterministic in-memory responses.

- [ ] **SCION-FINANCE-SOURCES-R900.3:** Prove crypto defaults call governed HTTP safety and market feeds default to the SDK stream bus. (`tests/test_finance_crypto.py::test_crypto_default_fetch_uses_governed_http_safety`; `tests/test_finance_feeds.py::test_market_feed_defaults_to_sdk_stream_bus`)

- [x] Refuse non-finite multi-asset prices and inversion overflow (SCION-FINANCE-SOURCES-R003.2).

- [x] Canonicalize FX currency codes before comparing the pair (SCION-FINANCE-SOURCES-R003.3).
- [x] Refuse invalid bar intervals before subscription (SCION-FINANCE-SOURCES-R900.9).

- [x] Require canonical FRED period and vintage dates (SCION-FINANCE-SOURCES-R001.5).

- [x] Refuse repeated FRED observation identities within a page (SCION-FINANCE-SOURCES-R001.6).

- [x] Require finite funding values and provider time (SCION-FINANCE-SOURCES-R900.11).

- [x] Fetch bounded exchange history windows across pages (SCION-FINANCE-SOURCES-R001.7).
- [x] Include the exchange client in the market extra (SCION-FINANCE-SOURCES-R001.8).
- [x] Validate calendar page shape, event identity, vintage and announcement time (SCION-FINANCE-SOURCES-R001.9).
