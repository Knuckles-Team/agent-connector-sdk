# Implementation design: finance sources

1. Define shared normalized source-record/provenance model at the SDK adapter boundary and keep generated graph DTOs at the sink. Document explicit interval/session/adjustment semantics.
2. Build stock history/quote/stream fixture adapter with bounded complete pagination, corporate actions, news/calendar metadata and licensing checks.
3. Add macro/vintage, FX, spot/futures, and dated real-estate adapters by extending the same SourceAdapter and manifest presets.
4. Add account read and CSV mapping-preview/import with stable activity IDs and replay-safe checkpointing.
5. Run offline conformance first; then opt-in licensed live probes and graph receipt qualification. Release each adapter independently once its own evidence is complete.

## Canonical multi-asset MCP sources

R003.1 binds the MCP source to a tenant and source identity. It validates each
FX, commodity or real-estate record before submission. For property values, it
compares valuation age with the configured freshness threshold. Provider APIs
and licensed live access remain outside this evidence. R003.4 adds offline provider evidence in Emerald Exchange. It covers FMP FX, Databento fixed futures, Twelve Data gold spot and ATTOM valuations. The served pack test runs the SDK adapter and graph replay with graph 2.27.6. It uses the candidate SDK. It does not test live credentials or licensing. Explicitly bounded delta sources refuse reconciliation and authoritative pages.

## Cross-provider market source contract (R001.2)

The SDK validates bounded CCXT candles and CoinMarketCap records.
It also validates FRED vintage observations and sourced FOMC announcements.
All use one MCP source contract before sink submission. It accepts only delta pages
and refuses reconciliation because a bounded query is not an authoritative
live set. Emerald exchange history and Bellwether finance streams are the
producer paths. Live licensed access is separate evidence.

## Calendar identity collision refusal (R001.3)

The normalizer preserves legacy event IDs. It refuses a page when one ID maps
to different announcement instants, instead of returning conflicting records.
This does not establish cross-page identity or migrate existing graph records.

R001.9 validates the calendar page and its identity fields before returning
records. It normalizes announcement times to UTC. It does not implement a
provider-specific API.

## Payment amount validation

For SCION-FINANCE-SOURCES-R900.4, the guard refuses negative or non-finite
amounts and budget limits. Spend recording rejects invalid or overflowing
amounts before changing counters. Zero spend remains valid.

## Confirmed payment binding (R900.8)

The payment client records a confirmed payment only when the supplied proof
matches the challenge and the configured wallet. A mismatch changes no spend
counter or history. This comparison does not establish the transaction on chain.
## Independent bar intervals

For R900.7, market feed subscriptions use one aggregator per symbol and bar
interval. Each tick updates every interval for its symbol. Subscribers to the
same interval share the same aggregator.

## Account source binding

R004.1 requires the account snapshot, positions and CSV activity to pass through
an account-bound SDK source adapter before the sink. The adapter validates each
record and rejects a different account. It keeps the served provider fields and
does not invent a provider event time. It submits non-authoritative delta pages
and refuses reconciliation, so one account read cannot withdraw another. The owner pack test replays the same
account, positions and CSV through the adapter into a real graph.

## Stock source conformance evidence

The stock SDK tests cover each source kind and the supported adjustment and
session labels. Emerald Exchange tests replay served stock provider fixtures
through the SDK adapter into a real graph. Owner fixtures cover the websocket
stream and exchange calendar. A deterministic generated stock illustration is
available from the adapter, identified as generated and non-official. It does
not depend on a third-party logo license. Live provider access remains separate.
The SVG composition follows the universal-skills
[canvas-design skill](https://github.com/Knuckles-Team/universal-skills/blob/main/universal_skills/skills/canvas-design/SKILL.md).
The adapter renders it locally from the validated symbol. Runtime needs no model
or network. The image is not a company logo or provider fact.

## Point-in-time liquidity composition

R005.1 reads the three FRED series from the graph using tenant-scoped query.
It requires the source identity, exact value text and actual capture time.
The SDK converts the published decimal units into exact fixed-point inputs.
The graph owns the versioned composite and heat-strip calculation. A missing
capture, ambiguous source, nonfinite value or unsafe precision refuses before
compute. Capture time is not the provider's historical publication time.
