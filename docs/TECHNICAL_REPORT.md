# Aletheia: A Governance Layer for LLM Investment Committees

**Status: research prototype. We claim a risk-governance contribution, not alpha.**

## Abstract

Multi-agent LLM systems for financial research are typically evaluated by output quality
(benchmark passes, report readability), not by whether their probabilistic claims resolve.
We built a decision engine in which every committee member, human-designed heuristic or
LLM, must emit *pre-registered, gradeable probabilistic forecasts* that are scored against
realized market outcomes net of trading costs, with influence (trust weights) earned purely
through calibration track record. A constitutional risk layer (position caps, leverage,
VaR, drawdown circuit breaker enforced daily) overrides any agent output. All decisions,
vetoes, and resolutions are recorded in a hash-chained, tamper-evident ledger.

Our headline results are deliberately mixed: across three equity markets (US large-cap,
Dow, Nikkei; Sep 2018 – Aug 2026), the governance machinery **consistently contains
drawdowns to 2.4–5.7%** (vs. 10–11% for a matched fixed-mix baseline, 31–37% for
buy-and-hold), and one mechanism, shrinkage-gated regime skills, improves return on
**3 of 3 markets** (median +0.7pp). However, the full system **fails to beat trivial
baselines on risk-adjusted return** in 2 of 3 markets, and one design lever (a
"mega-context" judge pass) *hurts* on our original market. We publish both. We also
fill the cell this architecture exists to fill: a real LLM, graded by eight years of
market outcomes through the member contract, **earns a durable, ranked seat, promoted
above its prior, last of five members** (Section 5).

## Positioning

Open multi-agent finance stacks (TradingAgents, FinRobot, FinGPT) operationalize debate
and research, but grade outputs with benchmarks or not at all; influence is asserted by
prompt role, not earned by track record; risk limits are prompt instructions that a
confident model can argue past. Aletheia inverts this: forecasting agents are graded by
the market itself (Brier/log/ECE), weights derive from calibration with Bayesian
shrinkage, and risk law executes in code between every proposal and every order. This is
the superforecasting discipline (Tetlock) applied to machine forecasters, with
constitutional-style hard limits.

## Architecture

| Mechanism | Contract | Module |
|---|---|---|
| Calibration-trust committee | Every member emits `(prob_up, expected_edge, confidence)`; graded net-of-cost; `trust_weight = f(mean Brier, n)` with shrinkage toward prior | `calibration/trust.py` |
| Adversarial falsification | Dedicated bear agent + binary thesis gate: theses die before capital allocation | `agents/gate.py` |
| Constitutional risk | 7 articles enforced daily in code; every veto named and logged; no agent can override | `core/constitution.py` |
| Decision ledger | Hash-chained append-only JSONL; tamper-evident; observability is replay | `calibration/ledger.py` |
| Regime skills | Recurring distillation of resolved decisions into (regime, probability-bucket) base rates; fires only when shrunk hit-rate clears the decision bar | `agents/skills.py` |
| LLM member (opt-in) | OpenAI-compatible endpoint, env-configured; every failure mode (no key, network, timeout, malformed, out-of-range) resolves to an explicit abstention | `agents/llm.py` |

Design invariants: walk-forward only (point-in-time snapshots; skills see resolved
history only); deterministic reruns (byte-identical reports); zero runtime dependencies
(stdlib only); everything decision-relevant is in the ledger.

## Evaluation methodology

- **Data**: FRED official keyless daily series (S&P 500, Nasdaq Composite, DJIA, Nikkei
  225, VIX, 2y/10y Treasury). Decision window Sep 2018 – Aug 2026; 60-session warmup;
  rebalance every 5 sessions; 21-session forecast horizon.
- **Grading**: a forecast counts as correct only if the realized move exceeded the
  round-trip cost (10 bps: 5 bps per side), agents earn credit for *tradable*
  edge, not epsilon drift.
- **No test-set tuning**: all constants (VIX thresholds 14/30, curve slope 1.5pp, skill
  shrinkage n=30, Kelly fraction 0.5, position cap 20%, VaR 2%) were fixed from design
  reasoning before measurement and are disclosed in source. Ablations are config toggles.
- **Reproduction**: single command, deterministic; the ladder below reproduces from the
  warm cache in ~15 s.

## Results

### 1. Mechanism ladder across markets (return deltas vs. full system)

Removing one mechanism at a time; positive number = the mechanism contributes return.

| Removed lever | S&P+NDX | DJIA | Nikkei | Record |
|---|---|---|---|---|
| − Skills | **−1.0pp** | **−0.7pp** | **−0.5pp** | skills help 3/3, median +0.7pp |
| − Macro knowledge (VIX/curve) | −3.3pp ret / **+0.7pp DD** | −0.1pp ret / **+0.8pp DD** | −0.1pp ret / **+0.5pp DD** | macro reduces maxDD 3/3 |
| − Mega-context judge pass | −1.9pp ret / −0.1pp DD | −0.1pp ret / +0.4pp DD | −0.1pp ret / +0.2pp DD | **context does not pay** |

Macro awareness is a risk decision, not a return decision: it buys 0.5–0.8pp of
drawdown reduction for ≈0 return cost on DJIA/Nikkei, but costs 3.3pp of return on the
S&P+NDX book. The mega-context pass, implemented because the "one agent with full
context" recipe is standard agent-building advice, *degrades* the original market and
is neutral elsewhere. We keep it behind a toggle and report it as a negative result.

### 2. Baseline comparison (the honest table)

| Market | System | Total | Sharpe | maxDD |
|---|---|---|---|---|
| S&P+NDX | buy-and-hold | +191.9% | 0.82 | 33.9% |
| | fixed 25% index + cash | +48.0% | **0.84** | 10.2% |
| | **Aletheia (full)** | +21.5% | 0.66 | **5.7%** |
| DJIA | buy-and-hold | +117.9% | 0.64 | 37.1% |
| | fixed 25% + cash | +29.5% | 0.65 | 10.7% |
| | **Aletheia (full)** | +10.0% | **0.75** | **2.4%** |
| Nikkei | buy-and-hold | +221.5% | 0.82 | 31.3% |
| | fixed 25% + cash | +55.4% | 0.78 | 10.7% |
| | **Aletheia (full)** | +12.2% | 0.65 | **4.8%** |

Read plainly: the system **wins on drawdown containment everywhere** (2.4–5.7% through
COVID-19 and the 2022 bear) and **wins Sharpe on 1 of 3 markets**. It loses to a
fixed index/cash mix on risk-adjusted return elsewhere. Anyone evaluating this as an
alpha machine should stop reading here, that is not the claim.

### 3. Calibration behavior, and a decomposition that cuts against us

Mean Brier across 3,080+ graded forecasts (net-of-cost grading): 0.2547 / 0.2686 / 0.2611
(S&P+NDX / DJIA / Nikkei), similar across markets, all in the "better than chance, far
from clairvoyant" band. The LLM member's eight-year grade lands in the same band and
next to the same peers (Section 5).
trust weights migrate measurably over the window (e.g., the bull agent earned weight
through the 2019–2021 expansion and ceded it in 2022; a poorly calibrated quant was
demoted to 0.671 in synthetic runs).

The skill book's headline cell, "calm regime, high-confidence call, 73.1% net-of-cost
hit rate (n=1071)", **does not survive conditioning**: the unconditional calm-regime
hit rate is 73.8%, so the probability-bucket contribution is −0.7pp (z = −0.37). Across
all eight populated (regime, bucket) cells with n ≥ 30, **zero exceed |z| = 2.8**
(α ≈ 0.005 under a Bonferroni-style correction; largest |z| = 2.78 for stressed/high,
which is *below* its regime base by 21pp). The global net-of-cost up-rate is 65.2%.

Honest interpretation: the skills mechanism's return contribution (3/3 markets above)
comes from **regime timing**, it steers the committee toward deploying in calm regimes,
where up-drifts clear the cost bar ~74% of the time, not from bucket-level predictive
power. The base-rate layer works as a deployment filter, not a probability refiner.
Whether that timing edge persists out-of-window is untested.

### 4. Out-of-window validation and uncertainty (added post-review)

**The skills timing edge does not replicate out-of-window.** On Nikkei 1990–2017, 28
years the mechanism never saw, spanning Japan's entire post-bubble bear, skills-on and
skills-off are identical: **+7.7% return, Sharpe 0.15, maxDD 6.5% both**. The in-window
3/3 record (Section 1) should be read as regime-fit, not persistent edge.

What did generalize is the risk layer: over 1990–2017 the governed committee returned
+7.7% with 6.5% max drawdown while the Nikkei index itself lost **−41.2%** with an
**81.8% max drawdown**. In a 28-year window where the index never recovered its 1989
high, the constitution kept the book alive and flat-ish, the intended behavior when no
edge exists.

**Uncertainty is wider than point estimates suggest.** Stationary-bootstrap 95% CIs on
Sharpe (2,000 resamples, ~21-day blocks): SPX+NDX 2018–2026 [0.06, 1.30]; DJIA 2018–2026
[0.16, 1.38]; Nikkei 1990–2017 [−0.22, 0.54]. No headline Sharpe in this report should
be quoted without its interval; the OOW interval includes zero.

### 5. An LLM graded by the market: the empty cell, filled

**A current-generation LLM earns a seat on the committee, and loses the top spot.**
We seated an open-weights 20B reasoning model (`gpt-oss:20b` served locally via Ollama,
`reasoning_effort: low`) through the standard member contract: pre-registered
probabilistic forecasts committed before evidence review, graded net-of-cost against
21-session S&P 500 outcomes across the full Sep 2018 – Aug 2026 window, trust-weighted
by the same calibration rule as the built-ins. 390 calls, 0 retries, 0 abstentions; the
resulting 5,044-entry ledger verifies end-to-end, with the SHA-256 chain recomputed
independently of the framework's own loader. (Method note: cloud free tiers proved
non-viable, Gemini's free tier now allows ~20 requests/day, so the run executed
locally, which also makes it exactly reproducible by anyone with the weights.)

| member | n | Brier | ECE | final trust weight |
|---|---|---|---|---|
| quant | 385 | 0.2684 | 0.1817 | 1.416 |
| bull | 385 | **0.2364** | 0.1401 | **1.590** |
| bear | 385 | 0.2393 | 0.1214 | 1.575 |
| judge | 385 | 0.2482 | 0.1118 | 1.526 |
| **llm** | 385 | 0.2701 | 0.1458 | 1.407 |

The committee **promoted the LLM above its uniform prior**: its weight rose from 1.0 to
1.407 and sat above the prior in 374 of 390 decisions (dipping to 0.863 early, peaking
at 1.473). But every specialized built-in out-graded it, and it finished last of five
in earned influence. It is demonstrably not noise (0.50 would be guessing; its
net-of-cost hit rate matches the book at 0.668) and better calibrated than the quant
member (ECE 0.146 vs 0.182), while carrying the worst Brier of the five.

The trajectory is the interesting part: per-third Brier runs **0.2621 → 0.2977 →
0.2508**, degradation concentrated in the 2021–2024 bear/chop, its best grading in
2024–2026. The trust mechanism did precisely what it exists to do: demoted the member
through its worst regime, never discarded it, and priced its recovery. Neither
worship nor exile, a real, ranked, earned seat.

Limitations, stated plainly: this is an open-weights 20B model, not a frontier API
model; one market; and the grading is the committee's own rule. Whether frontier
models outrank the specialized heuristics is the open question, and the contract +
runner exist to answer it.

### 6. Negative results (published deliberately)

1. The mega-context judge fusion (all-member + macro + cross-book context, bounded
   ≤10pp) reduced returns on the original market and is neutral-to-negative elsewhere.
2. The full system does not dominate trivial baselines on Sharpe in 2 of 3 markets.
3. An early adversarial gate design was a logical trap (any bear pressure ≥ the strict
   bar automatically breached it, killing 88/89 theses); the fix (gradient bar) is
   documented because such incentive traps are the failure mode this architecture exists
   to catch, including in itself.

## Limitations

- Three 8-year market histories, one run per cell; no confidence intervals yet (block
  bootstrap is planned). Windows overlap in regime (all contain COVID and the 2022 bear).
- All thresholds hand-set and disclosed; a sensitivity ridge over them is planned.
- The skill timing edge (Section 3) has not been tested out-of-window or on longer
  histories; the Nikkei series extends to 1949 and is the natural out-of-sample test.
- The LLM grading result (Section 5) is one open-weights 20B model, one market, graded
  under the committee's own rule; a frontier-API member and additional markets are
  untested. The member itself is fully governed (graded, weighted, abstention-only
  failure) in all cases.
- 5 bps transaction costs, index data only, USD-rate macro applied to the Nikkei book.

## Reproduction

```bash
pip install .[dev]
python -m pytest tests/ -q                  # 51 tests
python -m aletheia.cli backtest --start 2018-09-01 --end 2026-08-31 --ledger-out run_ledger.jsonl
python -m aletheia.cli report --path run_ledger.jsonl   # trust evolution, vetoes, skills, replayed from the ledger
python -m aletheia.cli verify-ledger --path run_ledger.jsonl
```

## What we would want from a lab collaboration

1. Independent review of the grading and walk-forward machinery (the ledger makes every
   decision mechanically auditable).
2. Extend the LLM grading study (Section 5) to frontier-API models and more markets:
   the contract and runner exist; the open question is whether frontier models
   outrank the specialized heuristics the way the 20B open-weights model did not.
3. Extension to more markets/decades and sub-period stability analysis.

## Post-review status

A structured review pass (see `REVIEW_FINDINGS.md`) corrected two doc-code
contradictions (cost assumption 10 bps round trip, per-market Brier range), documented a
≤4-session resolution-date wobble, added the out-of-window validation and bootstrap CIs
above, and found the look-ahead surfaces clean (provider clipping, skill distillation,
prompt construction, resolution timing). The skills out-of-window null (F4) supersedes
the in-window skills record wherever the two conflict.
