# Tasks: finance sources

- [x] Stock history, quote, stream, adjustment, corporate-action, profile, licensed logo, news and calendars (SDK-FINANCE-SOURCES-R002).
- [ ] FRED/ALFRED vintage and FOMC calendar plus other market feed sources (SDK-FINANCE-SOURCES-R001).
  - [x] Central-bank announcement calendar (`agent_connector_sdk.finance.central_bank_calendar`): one record per published vintage of a scheduled announcement, so a reschedule is a new record, never an overwrite (SDK-FINANCE-SOURCES-R001).
  - [ ] Exchange history retrieval fix and a CoinMarketCap market-data adapter (SDK-FINANCE-SOURCES-R001).
- [x] FX, commodity spot/futures and dated real-estate valuation adapters (SDK-FINANCE-SOURCES-R003).
- [x] Account/position reads and idempotent CSV import with preview (SDK-FINANCE-SOURCES-R004).
- [x] Macro and liquidity panels: FRED series, ETF flows, sentiment, on-chain, each tagged with source and observation time (SDK-FINANCE-SOURCES-R005).
  - [x] FRED/ALFRED macro series preserving reporting vintage (`agent_connector_sdk.finance.fred_series`) (SDK-FINANCE-SOURCES-R005).
  - [x] ETF fund-flow panel: net flow and AUM per fund per trading day (`agent_connector_sdk.finance.etf_flows`) (SDK-FINANCE-SOURCES-R005).
  - [ ] Versioned liquidity composite and heat-strip panel, sentiment data, and on-chain position data (SDK-FINANCE-SOURCES-R005).
- [ ] Attach exact merged commits, offline CI and opt-in licensed source receipts before acceptance.
