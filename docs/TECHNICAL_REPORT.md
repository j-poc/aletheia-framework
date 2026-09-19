# Aletheia: A Governance Layer for LLM Investment Committees

**Status: research prototype. We claim a risk-governance contribution, not alpha.**

## Abstract

Multi-agent LLM systems for financial research are typically evaluated by output quality
(benchmark passes, report readability), not by whether their probabilistic claims resolve.
We built a decision engine in which every committee member, human-designed heuristic or
LLM, must record gradeable probabilistic forecasts before outcomes are known. Forecasts
are scored against realized market outcomes net of assumed trading costs. Member
weights depend on historical Brier scores, but this version does not require a member
to outperform a simple forecast baseline. A constitutional risk layer checks position caps,
leverage, and VaR at rebalance, and the drawdown circuit breaker each session. All decisions,
vetoes, and resolutions are recorded in a hash-linked ledger.

After correcting rebalance accounting and the skill evidence path, the full system
returned +25.7%, +6.3%, and +10.2% on the S&P 500 plus Nasdaq Composite, Dow, and
Nikkei runs from late 2018 to August 2026. Maximum drawdowns were 3.6% to 5.9%, but
Sharpe was below a simple initial 25% index and 75% cash portfolio in all three
markets. Low drawdown alone does not establish that the constitutional risk rules add
value: the system often holds less market exposure. Regime skills add return in two
markets, subtract it in one, and make no difference in the 1990–2017 Nikkei run.
An earlier local LLM experiment remains a historical member-calibration result; its
committee-level numbers have not been rerun under this corrected engine.

## Positioning

Aletheia combines three testable mechanisms: later market outcomes grade each
probabilistic forecast, historical Brier scores change member weights with
small-sample shrinkage, and code checks risk limits before orders. The current
weight rule uses absolute scores, so a positive weight change does not establish
skill above a simple base-rate forecast. The evaluation below tests that distinction.

## Architecture

| Mechanism | Contract | Module |
|---|---|---|
| Calibration-trust committee | Every member emits `(prob_up, expected_edge, confidence)`; graded net-of-cost; `trust_weight = f(mean Brier, n)` with shrinkage toward prior | `calibration/trust.py` |
| Adversarial falsification | Dedicated bear agent + binary thesis gate: theses die before capital allocation | `agents/gate.py` |
| Constitutional risk | Order limits checked at rebalance; drawdown breaker checked daily; every veto named and logged | `core/constitution.py` |
| Decision ledger | Hash-linked JSONL with chain verification; a retained external head is needed to detect full recomputation | `calibration/ledger.py` |
| Regime skills | Recurring distillation of resolved decisions into (regime, probability-bucket) base rates; fires only when shrunk hit-rate clears the decision bar | `agents/skills.py` |
| LLM member (opt-in) | OpenAI-compatible endpoint, env-configured; every failure mode (no key, network, timeout, malformed, out-of-range) resolves to an explicit abstention | `agents/llm.py` |

The engine clips observations to each decision date and lets skills read only resolved
history. It does not retain historical FRED publication vintages, so a full
knowledge-time guarantee for macro series is unverified. Runs from the same cached
input are deterministic. The input bytes are identified by hashes in
[`data/source_manifest.json`](../data/source_manifest.json), but are not distributed.
Runtime dependencies are limited to the Python standard library.

## Evaluation methodology

- **Data**: cached FRED daily series (S&P 500, Nasdaq Composite, DJIA, Nikkei 225,
  VIX, 2y/10y Treasury). Requested window Sep 2018 to Aug 2026; trading starts after
  a 60-session warmup. The active start is Nov 28 for U.S. markets and Nov 30 for
  Nikkei. Rebalance every 5 sessions; forecast horizon nominally 21 sessions.
- **Grading**: a forecast counts as correct only if the realized move exceeded the
  round-trip cost (10 bps: 5 bps per side), agents earn credit for *tradable*
  edge, not epsilon drift.
- **Portfolio accounting**: yesterday's held weights earn today's close-to-close move;
  weights then drift with prices. At today's close, orders change weights and pay 5 bps
  on turnover. Cash earns zero; index dividends, funding, spread, impact, and tax are
  omitted. This is a price-index research simulation, not an executable strategy.
- **Baselines**: buy equal initial amounts of the named indices at the first active
  session and hold; or buy 25% of that portfolio and keep 75% cash at zero interest.
  Baselines use the same active dates as the engine and omit trading costs.
- **Uncertainty**: stationary bootstrap of daily portfolio returns, 2,000 resamples,
  mean block length 21 sessions, fixed seed 7. These intervals describe sampling
  variation of Sharpe, not confidence in a live strategy.
- **Reproduction**: `python3 -m aletheia.reproduce_report` verifies the local
  files against the source manifest before emitting the market matrix. A fresh
  FRED download may differ from these inputs because the series can change.

## Results

### 1. Mechanism ladder

Each row removes one lever from the full system. Returns are total returns over the
active window; a difference is a path observation, not a causal estimate across markets.

| Market | Full | No context | No macro | No skills | No three levers |
|---|---:|---:|---:|---:|---:|
| S&P 500 + Nasdaq Composite | +25.69% | +29.99% | +29.86% | +23.18% | +27.39% |
| Dow | +6.31% | +6.83% | +6.96% | +6.93% | +7.89% |
| Nikkei | +10.24% | +9.93% | +10.88% | +9.68% | +10.15% |

Skills contribute +2.51 percentage points on the U.S. pair, -0.62 on Dow, and +0.56
on Nikkei. The context pass costs 4.30 points on the U.S. pair. Macro inputs lower
max drawdown in all three runs by 0.77 to 1.12 points, but none of these results
establish a stable improvement out of sample.

### 2. Simple baselines on identical active dates

| Market | Portfolio | Total | Sharpe | Max drawdown |
|---|---|---:|---:|---:|
| S&P 500 + Nasdaq Composite | Equal initial buy and hold | +220.90% | 0.81 | 31.94% |
| | Initial 25% index / 75% cash | +55.22% | 0.80 | 12.11% |
| | Aletheia full | +25.69% | 0.67 | 5.48% |
| Dow | Buy and hold | +109.67% | 0.60 | 37.09% |
| | Initial 25% index / 75% cash | +27.42% | 0.62 | 10.37% |
| | Aletheia full | +6.31% | 0.43 | 3.64% |
| Nikkei | Buy and hold | +196.68% | 0.76 | 31.27% |
| | Initial 25% index / 75% cash | +49.17% | 0.74 | 10.15% |
| | Aletheia full | +10.24% | 0.50 | 5.88% |

The system's lower drawdowns coexist with lower returns and lower Sharpe in every
market. The 25% benchmark is a simple comparison, not an exposure-matched control.
These results support neither an alpha claim nor an isolated claim that the
constitution caused the drawdown difference.

### 3. Corrected calibration and skill evidence

Mean Brier scores for the full runs are 0.2550, 0.2685, and 0.2617, respectively.
The U.S. pair has 3,080 graded member and judge forecasts, but the skill book now
uses only 770 resolved fused judge decisions. The old 1,071-observation "calm/high"
cell pooled member forecasts and used the regime at resolution. It is invalid as
decision-time skill evidence. The corrected calm/high cell is 164 hits in 262
decisions (62.6% before shrinkage), with the regime measured when each call was made.
The corrected run logs 457 skill applications. Its observed return effect is mixed
across markets and zero in the historical Nikkei window.

The trust weights use each member's absolute Brier score. To test whether this
reflects useful forecasting skill, we compared each issued call with a rolling
base-rate probability `(prior up outcomes + 1) / (prior resolved outcomes + 2)`.
Only outcomes resolved by the issue date entered that baseline. On the 385
resolved calls per symbol, the S&P 500 baseline scored 0.2322 Brier versus
0.2684, 0.2364, 0.2393, and 0.2439 for quant, bull, bear, and the fused judge.
On Nasdaq Composite, the baseline scored 0.2431 versus 0.2826, 0.2505, 0.2555,
and 0.2636. Lower is better. Every committee forecast scored worse than this
simple comparator on both symbols. The current rule can still raise a member's
weight above its prior; that rise is not proof of predictive skill.

### 4. Longer Nikkei window and uncertainty

With the same 60-session warmup, the active Nikkei window is Apr 3, 1990 to
Dec 29, 2017. Both skill variants return +9.69%, Sharpe 0.17, with 6.64% max
drawdown. Buy and hold from that same active start returns -20.84% with 78.75%
max drawdown; the initial 25% index / 75% cash baseline returns -5.21% with
21.88% max drawdown. This is evidence of low realized exposure and loss containment
in this particular history. It does not isolate the contribution of each risk rule.

Stationary-bootstrap 95% intervals on full-system Sharpe are [0.04, 1.32] for the
U.S. pair, [-0.18, 1.03] for Dow, [-0.23, 1.21] for Nikkei 2018–2026, and
[-0.21, 0.55] for Nikkei 1990–2017. All include much weaker outcomes than their
point estimates. No difference-versus-baseline interval has been computed.

### 5. Archived local LLM experiment

The September 18 experiment seated `gpt-oss:20b` through the member contract on
the S&P 500. It made 390 calls, with 385 forecasts resolved, no abstentions, and
no retries. The archived ledger verifies as a hash chain. These observations came
from the earlier engine, before the accounting and skill corrections above. The
LLM's own forecast scores can be read as historical calibration evidence; the
committee's ranking and portfolio result must be rerun before being attributed
to the corrected build.

| Archived member | n | Brier | ECE | final trust weight |
|---|---|---|---|---|
| quant | 385 | 0.2684 | 0.1817 | 1.416 |
| bull | 385 | **0.2364** | 0.1401 | **1.590** |
| bear | 385 | 0.2393 | 0.1214 | 1.575 |
| judge | 385 | 0.2482 | 0.1118 | 1.526 |
| **llm** | 385 | 0.2701 | 0.1458 | 1.407 |

In that archived run, the LLM's Brier was 0.2701 and ECE 0.1458. Its raw trust
weight ended at 1.407. The experiment shows that the member contract can grade a
local model over a long history. It does not show model edge, a current committee
ranking, or a current portfolio result. One model and one market are insufficient
for a broader model comparison.

### 6. Negative results (published deliberately)

1. The full system loses to the initial 25% index / 75% cash baseline on Sharpe
   in all three 2018–2026 markets.
2. Skills help on two markets, hurt on Dow, and make no difference in the longer
   Nikkei window. The previous 73% skill claim used invalid evidence.
3. The context pass reduces return by 4.3 percentage points on the U.S. pair.

## Limitations

- The three recent market histories overlap in regime; each mechanism has one run
  per market. Bootstrap intervals do not correct design selection or multiple testing.
- FRED observations are clipped by date but not by historical release vintage.
  Macro revision leakage remains possible. The 21-session resolution date can also
  shift on symbol-calendar gaps; see `REVIEW_FINDINGS.md`.
- Thresholds are hand-set. There is no exposure-matched or equal-risk control,
  sensitivity ridge, dividends, financing, or live execution evidence.
- Nikkei uses U.S. interest-rate inputs. The LLM comparison is archived and has not
  been rerun on the corrected engine.
- The exact FRED cache used here is local and untracked. Reproducing these exact
  numbers requires the same input bytes, identified in the source manifest. The
  underlying series carry third-party rights; the raw files are not distributed.
  The ledger has no externally anchored head.

## Reproduction

```bash
pip install .[dev]
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/ -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 python3 -m aletheia.reproduce_report > corrected_report.json
python3 -m aletheia.cli backtest --start 2018-09-01 --end 2026-08-31 --ledger-out corrected_ledger.jsonl
python3 -m aletheia.cli verify-ledger --path corrected_ledger.jsonl
```

## What we would want from a lab collaboration

1. Independent review of the grading and walk-forward machinery (the ledger makes every
   decision mechanically auditable).
2. Extend the LLM grading study (Section 5) to frontier-API models and more markets:
   the contract and runner exist; the open question is whether frontier models
   outrank the specialized heuristics the way the 20B open-weights model did not.
3. Extension to more markets/decades and sub-period stability analysis.

## Post-review status

The September 19 correction fixed rebalance-day return omission, drifted held weights,
included initial order costs in total return, and made skill evidence use only fused
decisions with the regime known at issue time. The previous market matrix and skill
cell are superseded by the numbers above. `REVIEW_FINDINGS.md` records the findings.
