# Test specification: finance sources

| ID | Fixture/action | Required assertion |
|---|---|---|
| FS-01 | Stock history across >365 bars and >one provider page | Complete requested interval and deterministic order; no silent truncation. |
| FS-02 | Unsupported interval or missing pre/post session data | Typed refusal or partial status, never implicit 1-day fallback. |
| FS-03 | Split/dividend action and raw/adjusted bars | Both adjustment modes labeled; no mixed series or look-ahead application. |
| FS-04 | News, earnings, dividend, FRED/ALFRED vintage | Event and availability timestamps preserved; original source and entitlement attached. |
| FS-05 | FX inversion, spot versus expiring future, stale property value | Direction, contract/roll, and staleness explicit; impossible combinations refuse. |
| FS-06 | CSV preview with ambiguous mapping/currency, then import twice | Preview requires resolution. Identical source digest/row IDs yield one activity. Changed file is a new version. |
| FS-07 | 429, timeout, partial page, missing license or credential | Bounded retry or typed refusal. No checkpoint advance, secret leak or fabricated complete record. |
| FS-08 | Contributor-owned licensed provider and graph service | Redacted receipt binds source digest, entitlement, instrument, interval, completeness and checkpoint. |

R001.3 rejects two different announcement instants that share a legacy page identity.
Equivalent timestamps for the same instant remain valid.

Offline source PRs run fixture pytest and repository quality hooks (Ruff, mypy, CCCC, Dupehound, KISS). FS-08 is an opt-in acceptance probe and reports **NOT RUN** without licensed provider access.

R900.8 rejects a missing proof and each field mismatch before recording spend.
The tests also retain the matched challenge and proof success path.
R900.7 runs the production market bus with a controlled clock. Two bar
intervals for one symbol each receive their own completed bars.

R002.1 remains open: the existing synthetic bar-page tests exercise normalization and labels, not the complete source-adapter coverage required by R002.

R005.1 remains open: current FRED and ETF normalization tests do not prove the remaining macro and liquidity panels.

R001.1 tests non-finite FRED values through source normalization and direct model construction, while ordinary finite observations remain accepted.

R003.1 remains open: existing FX, commodity and real-estate model tests do not exercise source adapters.

R004.1 remains open: synthetic mapping and stable identifiers do not prove real source reads or durable re-import.
- `SDK-FINANCE-SOURCES-R003.2`: `tests/test_finance_records.py` checks non-finite FX and commodity prices and overflow on FX inversion.

- `SDK-FINANCE-SOURCES-R003.3`: `tests/test_finance_records.py` checks FX currency normalization and refusal of malformed or identical currency codes.
- `SDK-FINANCE-SOURCES-R900.9`: `tests/test_finance_feeds.py` covers invalid intervals and refusal without a subscription.


R002.2 rejects non-finite values across all bar, quote and corporate action fields.

R004.2 tests non-finite balances, position quantities, prices and activity amounts through normalization.
