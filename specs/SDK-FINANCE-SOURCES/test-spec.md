# Test specification: finance sources

| ID | Fixture/action | Required assertion |
|---|---|---|
| FS-01 | Stock history across >365 bars and >one provider page | Complete requested interval and deterministic order; no silent truncation. |
| FS-02 | Unsupported interval or missing pre/post session data | Typed refusal or partial status, never implicit 1-day fallback. |
| FS-03 | Split/dividend action and raw/adjusted bars | Both adjustment modes labeled; no mixed series or look-ahead application. |
| FS-04 | News, earnings, dividend, FRED/ALFRED vintage | Event and availability timestamps preserved; original source and entitlement attached. |
| FS-05 | FX inversion, spot versus expiring future, stale property value | Direction, contract/roll, and staleness explicit; impossible combinations refuse. |
| FS-06 | CSV preview with ambiguous mapping/currency, then import twice | Preview requires resolution; identical source digest/row IDs yield one activity; changed file is a new version. |
| FS-07 | 429, timeout, partial page, missing license or credential | Bounded retry or typed refusal; no checkpoint advance, secret leak or fabricated complete record. |
| FS-08 | Contributor-owned licensed provider and graph service | Redacted receipt binds source digest, entitlement, instrument, interval, completeness and checkpoint. |

Offline source PRs run fixture pytest and repository quality hooks (Ruff, mypy, CCCC, Dupehound, KISS). FS-08 is an opt-in acceptance probe and reports **NOT RUN** without licensed provider access.
