# Tasks: finance sources

- [ ] Stock history, quote, stream, adjustment, corporate-action, profile, licensed logo, news and calendars (SDK-FINANCE-SOURCES-R002).
- [ ] FRED/ALFRED vintage and FOMC calendar plus other market feed sources (SDK-FINANCE-SOURCES-R001).
  - [x] Central-bank announcement calendar (`agent_connector_sdk.finance.central_bank_calendar`): one record per published vintage of a scheduled announcement, so a reschedule is a new record, never an overwrite (SDK-FINANCE-SOURCES-R001).
  - [ ] Exchange history retrieval fix and a CoinMarketCap market-data adapter (SDK-FINANCE-SOURCES-R001).
- [ ] FX, commodity spot/futures and dated real-estate valuation adapters (SDK-FINANCE-SOURCES-R003).
- [ ] Account/position reads and idempotent CSV import with preview (SDK-FINANCE-SOURCES-R004).
- [ ] Macro and liquidity panels: FRED series, ETF flows, sentiment, on-chain, each tagged with source and observation time (SDK-FINANCE-SOURCES-R005).
- [ ] Attach exact merged commits, offline CI and opt-in licensed source receipts before acceptance.
