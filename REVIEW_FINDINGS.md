# Independent review findings — 2026-09-18

Scope: re-derived report numbers from saved run artifacts (`.cache/multi_market_ladder.json`,
`run_ledger.jsonl`), audited look-ahead surfaces (provider clipping, prompt construction,
skill distillation, resolution timing), checked doc-vs-code consistency. Review performed
by the same author as a structured self-audit; treat "independent" as aspirational until a
second person repeats this pass. Each finding: severity, status, evidence.

## Findings

### F1. Cost assumption misstated in the report — FIXED
**Severity: medium (doc-code contradiction).** The report claimed grading is net of
"5 bps side, 5 bps total." The code (`engine/backtest.py` line 108:
`rt_cost = 2.0 * cost_bps / 10_000` with `cost_bps=5.0`) grades against a **10 bps
round trip** (5 bps per side). Order-simulation costs are 5 bps on turnover; forecast
grading is 10 bps round trip. Report corrected.

### F2. "Mean Brier ≈ 0.254 in every market" is drift — FIXED
**Severity: low.** Actual full-system values from the saved matrix: SPX+NDX 0.2547,
DJIA 0.2686, Nikkei 0.2611. The qualitative claim (similar across markets) holds; the
single number did not. Report now quotes the range.

### F3. Resolution-date wobble up to 4 sessions — DOCUMENTED, OPEN
**Severity: low (measurement imprecision, not leakage).** Forecasts mature at the H-session
mark; a symbol's resolution bars are filtered to `date <= as_of`. Around calendar
bottlenecks (weekends/holidays) a resolution window can shift by up to 4 sessions, so
"21-day return" is sometimes measured over 17–25 sessions. No future information enters
(the resolve-day price is always ≤ resolve date). A fix would pin resolution to the
H-th *session* per symbol; deferred as it changes every graded number.

### F4. Skills edge does not replicate out-of-window — NEW RESULT, ADDED TO REPORT
**Severity: high for the skills claim.** Nikkei 1990–2017 (untouched by all prior runs):
skills on/off differ by **0.0pp** return (both +7.7%, Sharpe 0.15, maxDD 6.5%). The
in-window effects (+1.0/+0.7/+0.5pp on 3 markets, 2018–2026) do not survive a regime the
mechanism never saw. The honest statement: the skills mechanism's contribution is
in-window regime timing, not a persistent edge.

### F5. Bootstrap CIs widen honest uncertainty — ADDED TO REPORT
Stationary bootstrap (2000 resamples, ~21-day blocks) 95% CIs on Sharpe:
SPX+NDX [0.06, 1.30]; DJIA [0.16, 1.38]; Nikkei-1990s OOW [−0.22, 0.54].
Every interval includes materially worse outcomes; the OOW interval includes 0.

### F6. Look-ahead audit — CLEAN
Checked: provider clips every series to `as_of`; skills distill only from ledger
resolutions with `as_of >= forecast + horizon`; LLM prompt embeds only bars dated ≤
decision date (test-enforced); no global state crosses runs. No violation found.

### F7. Verified artifacts
- Ladder deltas in the report reproduce exactly from the saved 15-cell matrix.
- `run_ledger.jsonl` verifies (hash chain OK, 8,328 entries).
- Baselines (buy-and-hold, fixed-mix) recomputed from the same provider data as the engine.
