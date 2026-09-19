# Independent review findings, 2026-09-18

Scope: re-derived report numbers from saved run artifacts (`.cache/multi_market_ladder.json`,
`run_ledger.jsonl`), audited look-ahead surfaces (provider clipping, prompt construction,
skill distillation, resolution timing), checked doc-vs-code consistency. Review performed
by the same author as a structured self-audit; treat "independent" as aspirational until a
second person repeats this pass. Each finding: severity, status, evidence.

## Findings

September 19 update: the earlier market matrix and skill statistics below are
historical artifacts. The corrected results are in `docs/TECHNICAL_REPORT.md` and
can be recomputed with `python3 -m aletheia.reproduce_report`.

### F1. Cost assumption misstated in the report, FIXED
**Severity: medium (doc-code contradiction).** The report claimed grading is net of
"5 bps side, 5 bps total." The code (`engine/backtest.py` line 108:
`rt_cost = 2.0 * cost_bps / 10_000` with `cost_bps=5.0`) grades against a **10 bps
round trip** (5 bps per side). Order-simulation costs are 5 bps on turnover; forecast
grading is 10 bps round trip. Report corrected.

### F2. "Mean Brier ≈ 0.254 in every market" is drift, FIXED
**Severity: low.** Actual full-system values from the saved matrix: SPX+NDX 0.2547,
DJIA 0.2686, Nikkei 0.2611. The qualitative claim (similar across markets) holds; the
single number did not. Report now quotes the range.

### F3. Resolution-date wobble up to 4 sessions, DOCUMENTED, OPEN
**Severity: low (measurement imprecision, not leakage).** Forecasts mature at the H-session
mark; a symbol's resolution bars are filtered to `date <= as_of`. Around calendar
bottlenecks (weekends/holidays) a resolution window can shift by up to 4 sessions, so
"21-day return" is sometimes measured over 17–25 sessions. No future information enters
(the resolve-day price is always ≤ resolve date). A fix would pin resolution to the
H-th *session* per symbol; deferred as it changes every graded number.

### F4. Skills edge does not replicate out-of-window, NEW RESULT, ADDED TO REPORT
**Severity: high for the skills claim.** The corrected Nikkei 1990–2017 comparison
still shows **0.0pp** skill contribution (both +9.69%, Sharpe 0.17, max drawdown
6.64%). The corrected recent-market effects are +2.51pp on the U.S. pair,
-0.62pp on Dow, and +0.56pp on Nikkei. There is no demonstrated persistent edge.

### F5. Bootstrap CIs widen honest uncertainty, ADDED TO REPORT
The corrected stationary bootstrap (2000 resamples, mean 21-session blocks) gives
95% CIs on Sharpe: U.S. pair [0.04, 1.32], Dow [-0.18, 1.03], recent Nikkei
[-0.23, 1.21], and 1990–2017 Nikkei [-0.21, 0.55].
Every interval includes materially worse outcomes; the OOW interval includes 0.

### F6. Earlier look-ahead audit, SUPERSEDED
The earlier pass correctly found observation-date clipping, but missed that skill
resolutions were tagged with the regime at the resolution date. That label was used
to train a lookup later queried with the regime at decision time. F9 fixes this.
The FRED cache also stores current series values, not historical publication vintages,
so a complete knowledge-time audit remains open.

### F7. Earlier verified artifacts, HISTORICAL
The old 15-cell matrix and 8,328-entry ledger remain hash-valid records of the old
engine. They are superseded as evidence for current performance. The corrected
report script uses the same active dates for the system and its simple baselines.

### F8. Rebalance-day portfolio return omitted, FIXED
**Severity: high for every performance comparison.** The decision cycle reset held
positions' reference prices before the daily mark, dropping that day's return on
every rebalance. It also left held weights fixed between orders without charging
for the implicit daily rebalancing, and total return omitted the first order cost.
The engine now marks prior holdings first, lets weights drift, applies orders at the
close, and computes total return from initial capital. A steady-price-path check
failed before the fix because held returns disappeared on rebalance days. Its final
daily-rebalance regression passes after the fix. The full 15-cell market matrix was
rerun from the local FRED cache.

### F9. Skill evidence mixed members and used resolution-time regime, FIXED
**Severity: high for the skill claim.** All 3,080 resolutions in the old U.S. pair
ledger carried `skill_kind=committee`; the distiller consumed every member and the
judge. The recorded regime came from the resolution snapshot, not from forecast
issuance. Regression checks now require only fused judge decisions and the issue-time
regime. The corrected U.S. pair book has 770 decision observations and 457 skill
applications. The previous 73% skill cell is invalid.
