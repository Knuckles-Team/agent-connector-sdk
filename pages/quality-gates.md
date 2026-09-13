# Quality gates

Every commit and push runs the combined scan suite in `.pre-commit-config.yaml`;
CI runs the release-critical subset in `.github/workflows/release.yml`.

## Scanners

| Scanner | Version | Scope | Rule |
|---|---|---|---|
| cccc | 1.6.0 | staged package Python | no new or worsened function above cyclomatic 10 or cognitive 15 |
| KISS | 0.4.10 | staged package Python | `.kiss/kiss.toml`, findings attributable to the diff |
| dupehound | 0.1.2 | changed functions | no new function clones |
| jscpd | 5.0.16 | pushed range and full tree | no new copied blocks; census printed |
| scanner census | cccc and KISS | every package module | zero findings, absolutely |

Scanner versions are verified before each run; a missing or different binary
stops the gate rather than passing it.

## Wiring

| Gate | Fails when |
|---|---|
| orphan modules | a package module is reachable from no public module, entry point or import |
| public API tested | a public name is used by no test |

## Other gates

Secret history, the security and garbage sanitizer, tracked privacy, root
hygiene, `.gitignore` convergence, OSV dependency audit, `uv lock --locked`,
supply-chain pinning, the phase-direction check, stubs, environment reads outside
`config.py`, stdout writes in served code, swallowed errors, import cycles,
event-loop blocking, ruff, mypy (strict), bandit, codespell, vulture, the test
suite, the strict site build, the wheel build, and a replay of the CI jobs.

The only stubs allowed are the two epistemic-graph sink methods that wait for
RF-ADR-009 W1; the stub gates print them as NOT DONE.
