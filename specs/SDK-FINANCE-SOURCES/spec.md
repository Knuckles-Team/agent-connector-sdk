# Qualified finance source adapters

**Program IDs:** EH-412, EH-701, EH-709, EH-713.
**Owner:** agent-connector-sdk contract and source adapter APIs; each vendor connector owns its credentials and API implementation. **Delivery state:** SPECIFIED. **Acceptance state:** OPEN.

## Outcome

Finance consumers receive source data with instrument identity, entitlement, time basis, adjustment policy, completeness, and provenance explicit. The first vertical slice covers stocks and ETFs; later slices add FX, metals/commodities, real-estate valuations, and account import. The SDK supplies shared bounded pagination, credentials, transport, manifest presets, provenance and data-quality checks. Trading decisions, portfolio accounting, chart rendering, strategy evaluation and order execution belong to their owners.

## Canonical adapter records

All records include `tenant_id`, `source_id`, `provider`, `instrument_id`, `source_event_id`, `event_time_utc`, `observed_at_utc`, `schema_version`, `license_tag`, and `source_digest`. OHLCV bars additionally include `timeframe`, `session_calendar`, `currency`, `adjustment_mode`, and `completeness` (`COMPLETE`, `PARTIAL`, `GAP`). Quotes include bid/ask and quote timestamp. Corporate actions include ex-date/effective date, type and adjustment factor. Account activities include account identity, broker event ID or source-file digest + row identity, action, signed quantity, price, fees, currency and settlement time. Real-estate valuations include valuation date, method/source, currency, and staleness. These are SDK-side normalized source records; durable graph schemas and finance calculations are owned by the graph service. Generated graph-client DTOs must be used at the sink boundary rather than copied into this repository.

`SourceAdapter` discovery declares supported asset class, interval/date-range limits, session calendar, entitlement, rate limit, adjustment semantics, and whether streams are historical or live. An unsupported interval, missing entitlement, unlicensed logo, absent extended-hours data, or incomplete page yields an explicit typed outcome, never a silent default. Pagination continues until the requested inclusive/exclusive interval is covered or a named incompleteness result is returned; no arbitrary first-50/first-365 truncation. Historical and live events share identity and deduplication rules.

For stocks, a vendor adapter supports history/quotes/streams with split/dividend adjustments, regular and pre/post-market flags, profile/fundamentals, licensed logos, news and earnings/dividend calendars (EH-701). Macro feeds such as FRED/ALFRED and a central-bank calendar preserve vintage and announcement time (EH-412). FX quotes identify base/quote and rate direction; gold/commodities distinguish spot from futures contract, expiry and explicit roll rule; real estate is a dated, potentially stale valuation rather than a live market quote (EH-709). Broker account/position reads and CSV activity import provide a mapping preview, reject ambiguous columns/currencies, and use stable provider event ID or file digest plus row ID so re-import is idempotent (EH-713).

The connector uses SDK `http/`, `credentials/`, `runner/`, `manifest/`, and `ports/source_adapter.py`; it never writes directly into graph storage. Credential references, entitlements and source licensing are validated before network calls. Provider outages, 429 retry-after, stale data, and partial pages preserve the last accepted checkpoint and report typed status to the caller.

## Portable development and evidence

Run `uv sync`; use deterministic recorded or synthetic responses with no paid key for offline conformance. A contributor can bring their own provider credential reference for live acceptance.

| Gate | State | Evidence |
|---|---|---|
| Exact merged adapter contracts | OPEN | Pending commit |
| Offline provider fixture conformance | OPEN | Pending CI run |
| Licensed live provider and graph receipt | OPEN | Pending redacted provenance/entitlement receipt |

**LANDED** requires exact merged source. **ACCEPTED** requires all test cases below with licensed source and graph receipt; no backtest or trade-performance claim follows from that acceptance.
