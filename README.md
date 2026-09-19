# Aletheia

**A calibration-governed AI investment framework.**

> **Evaluating this research?** Start with [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md),
> the research write-up with cross-market results, simple-baseline comparisons, negative
> results, and limitations. This README documents the system; the report grades it.

Most "AI investing" stacks today, including the multi-agent research patterns emerging from
the major labs, share one architecture: capable models research a market, debate, and
produce a recommendation. The missing layer is *governance*: nothing tracks whether the
models were actually right, nothing lets them earn or lose influence, and nothing structurally
prevents a confident model from taking excessive risk.

Aletheia is that missing layer, built as a complete decision engine:

| Mechanism | What it does | Where |
|---|---|---|
| **Calibration-trust committee** | Every agent emits a *gradeable probabilistic forecast*. Outcomes are scored (Brier, log score, ECE); voting weights respond to absolute historical Brier scores, shrunk toward the prior while samples are small. The present rule does not require skill above a base-rate forecast. The judge fuses member votes with bounded context (macro state, regime, cross-symbol conviction, skill recall; ≤10pp total shift, every adjustment logged). | `aletheia/calibration/trust.py`, `aletheia/agents/committee.py`, `aletheia/agents/context.py` |
| **Adversarial falsification gate** | A dedicated bear agent exists to *kill* theses, not to balance debate. A thesis only reaches capital if it survives: bear pressure below the bar AND no contradictory quant momentum evidence. | `aletheia/agents/gate.py` |
| **Constitutional risk layer** | Seven articles of hard risk law, position caps, leverage cap, falsification gate, drawdown circuit breaker (enforced **daily**, not just at rebalance), cooldown, daily VaR cap, and a drawdown-budget scaler. Enforced in code on the order pipeline; no agent can argue past it, and every veto is logged. | `aletheia/core/constitution.py` |
| **Hash-linked decision ledger** | Every forecast, thesis, veto, order, and resolution is linked by SHA-256. `verify()` catches broken links or altered entries; detecting a complete recomputation requires a separately retained head hash. | `aletheia/calibration/ledger.py` |
| **Walk-forward governance engine** | The `Committee` owns forecasts, gating, fusion, and skill recall. The engine owns daily marking and drawdown checks, plus sizing, other risk checks, order costs, and grading at rebalance. Observations are clipped to the decision date; historical FRED release vintages are not retained. | `aletheia/engine/backtest.py` |
| **Regime skill book** | Distills resolved fused decisions by the regime known when each forecast was issued. It sees only resolved history, shrinks rates to a prior, and logs every application. The corrected book has 770 decision observations in the U.S. pair run. | `aletheia/agents/skills.py` |
| **LLM member (opt-in)** | An OpenAI-compatible model seats on the committee through the *same* agent contract: its probabilistic forecast is recorded before the outcome, then graded and weighted like the built-in members. Missing configuration, network error, timeout, malformed output, and out-of-range probability produce an explicit abstention. | `aletheia/agents/llm.py` |
| **Ledger-native observability** | Trust-weight evolution, veto breakdown by article, and the live skill book, all replayed from the hash-chained ledger itself, not a parallel telemetry pipeline. | `aletheia/observability.py` |

```
                      ┌──────────────────────────────────────┐
                      │            DataProvider              │
                      │   FRED (real, keyless) / Synthetic   │
                      └──────────────┬───────────────────────┘
                                     │ observation-date-clipped snapshot
        ┌────────────────────────────┼────────────────────────────┐
        │                     DECISION DAY                        │
        │  quant ─┐                                               │
        │  bull ──┼─ forecasts → falsification gate → thesis      │
        │  bear ──┘                     │                         │
        │                        judge (trust-weighted fusion)    │
        │                               │ proposal                │
        │                    RiskGovernor (Constitution)          │
        │                     vetoes │ approved weights           │
        └────────────────────────────┼────────────────────────────┘
                                     │
              every day: mark-to-market → daily breaker check
                                     │
                    DecisionLedger (hash-chained, append-only)
                                     │
              resolution at horizon H → trust weights update
```

## Quickstart

```bash
# full committee on real market data (FRED: S&P 500 + Nasdaq, ~8 years)
python3 -m aletheia.cli backtest --start 2018-09-01 --end 2026-08-31 --ledger-out corrected_ledger.jsonl

# offline, fully reproducible synthetic market
python3 -m aletheia.cli backtest --synthetic --seed 7

# ablation: what each governance layer is worth
python3 -m aletheia.cli ablation --synthetic

# verify a decision ledger's integrity
python3 -m aletheia.cli verify-ledger --path corrected_ledger.jsonl

# observability report, replayed from the ledger
python3 -m aletheia.cli report --path corrected_ledger.jsonl

# recompute the report's market matrix from the exact locally held input files
python3 -m aletheia.reproduce_report

# run the test suite
python3 -m pytest tests/ -q
```

Runs are **deterministic**: same data + same seed → an identical report, byte for byte
(verified by running the engine twice in-process). The ledger's *content*, every
sequence, kind, payload, and hash chain, is deterministic too; only the wall-clock
`ts` stamp on each entry differs between runs, which is exactly what an audit trail
should record.

## The constitution

| Art. | Clause | Default |
|---|---|---|
| I | Max single position | 20% |
| II | Max gross leverage | 1.5× |
| III | Thesis must survive falsification gate | on |
| IV | Drawdown circuit breaker (daily check) | 15% |
| V | Cooldown after breach, no new risk | 5 days |
| VI | One-day 95% VaR cap | 2% |
| VII | Drawdown-budget exposure scaling | silent < 80% budget |

## Honest results

The current market matrix below can be rerun with
`python3 -m aletheia.reproduce_report` from the exact FRED cache files listed in
[`data/source_manifest.json`](data/source_manifest.json). The raw source files
are not distributed because their reuse rights are not established.

**Corrected real-data run (FRED, S&P 500 + Nasdaq Composite, active window
Nov 2018 to Aug 2026):** +25.7% total return, Sharpe 0.67, max drawdown 5.5%.
The comparable initial 25% index / 75% cash baseline returned +55.2%, Sharpe 0.80,
with 12.1% max drawdown. Across the Dow and Nikkei runs, the full system also had
lower drawdown and lower Sharpe than this simple baseline. Lower exposure is part of
the drawdown explanation; these comparisons do not isolate the risk layer's effect.

**Grading is net of assumed trading costs**: a forecast counts as right if the move
exceeds the 10 basis point round-trip threshold. The corrected U.S. pair run has
457 skill applications, based only on resolved fused decisions.

**The corrected performance ladder** (one lever removed at a time):

```
Full: skills + macro + context        ret +25.69%  sharpe 0.67  maxDD 5.48%
  no context                          ret +29.99%  sharpe 0.75  maxDD 5.82%
  no macro                            ret +29.86%  sharpe 0.73  maxDD 6.60%
  no skills                           ret +23.18%  sharpe 0.64  maxDD 5.34%
  no context, macro, or skills        ret +27.39%  sharpe 0.71  maxDD 5.85%
```

Skills add 2.5 percentage points on this path, subtract 0.6 points on Dow, add 0.6
points on Nikkei, and add nothing on the 1990–2017 Nikkei holdout. The context pass
reduces the U.S. pair's return by 4.3 points. These are observations from historical
paths, not evidence of persistent edge.

**Synthetic (regime-switching GBM):** useful for integration checks, not evidence of
market edge. See the [technical report](docs/TECHNICAL_REPORT.md) for the corrected
matrix, baselines, uncertainty intervals, and limitations. Recompute them with
`python3 -m aletheia.reproduce_report` from the cached FRED data.

The demonstrated result is a working forecasting and risk-governance research system.
Its investment advantage remains unproven. In the U.S. pair run, all members and
the fused judge scored worse than a rolling base-rate forecast that used only
outcomes resolved by each decision date; see the [technical report](docs/TECHNICAL_REPORT.md).

## What the component comparisons show

The corrected comparisons above measure the contribution of context, macro inputs,
and skills on each historical path. Their effects are mixed. None establishes a
stable forecasting improvement, and the trust rule still needs a base-rate gate.

## Lessons applied (from building agents in production)

Several design choices deliberately incorporate, or diverge from, hard-won lessons
from production agent building (e.g. Vercel's data-science-agent journey):

1. **Evals can lie.** Vercel's agent aced 30 internal evals and still failed real users.
   Aletheia grades against later market observations using a cost threshold. Synthetic runs are
   treated as smoke tests, never as evidence of edge.
2. **Skills from history, but governed.** Their recurring job distills past queries into
   skills so agents don't start from nothing. Aletheia distills *resolved decisions* into
   regime base rates, but skills must clear the decision bar through shrinkage, fire
   only on walk-forward data, and log every application to the ledger. Accumulated
   context can inherit an agent's biases. The current trust rule does not prevent
   that unless its forecasts beat an appropriate baseline.
3. **Observability is replay, not extra plumbing.** One append-only event log serves as
   audit trail, training data for skills, and the source for all reporting.
4. **Filesystem > bespoke pipelines.** Where an agent in this stack needs breadth
   (future LLM members), the plan is minimal primitives, read/write/execute in a
   data sandbox, not prescriptive hand-mapped tool chains.

## The LLM member

Frontier models join the committee governed, not trusted. With `--llm` (or `llm_member=`),
an OpenAI-compatible endpoint is asked for one JSON object per symbol per decision day,
`{"prob_up", "confidence", "expected_edge", "rationale"}`, using observations clipped
to the decision date (other members appear by name, never by their views). Historical
publication vintages for FRED macro series are not retained.
The call is recorded before any committee debate sees it, then graded net-of-cost and
trust-weighted exactly like the built-in members; a confidently wrong model is demoted by the
same math that demotes anything else.

Configuration is environment-only, read at one boundary:

```bash
export ALETHEIA_LLM_API_KEY=...     # required; absent -> member abstains
export ALETHEIA_LLM_BASE_URL=...    # default https://api.openai.com/v1
export ALETHEIA_LLM_MODEL=...       # default gpt-4o-mini
python3 -m aletheia.cli backtest --synthetic --llm
```

**Honest status:** tests cover the grading, trust, and abstention paths with a
deterministic stub. An earlier local Ollama run graded `gpt-oss:20b` over the S&P
history; its committee-level result has not been rerun on this corrected engine.
The optional cloud API path has not been exercised here. The environment-gated
live smoke test is skipped without configuration.

## Data

`FredProvider` pulls official keyless daily data from the St. Louis Fed (S&P 500, Nasdaq
Composite, VIX, 2y/10y Treasury) with a disk cache. Yahoo Finance was rate-limiting (HTTP
429) this environment, and Stooq is bot-walled, FRED is the robust keyless choice. To plug
in any other feed (broker API, yfinance, vendor), implement `DataProvider.get_snapshot()`.

**Offline & cold-start.** The provider never silently degrades to empty data: with a
populated cache (`.cache/fred/`, one CSV per series) it is fully offline-capable; with no
cache and no network it raises an actionable error naming the series and the fix, rather
than feeding the committee an empty tape. Pre-populate once with network access, then run
anywhere:

```bash
python3 -c "from aletheia.data.providers import FredProvider; \
  FredProvider(cache_dir='.cache/fred').get_snapshot(['SPX'], __import__('datetime').date(2026,1,1))"
```

## Roadmap

- **LLM member hardening**: the seat exists and is governed (see above); what remains is
  validation against real endpoints, richer prompt state, and measuring whether its
  calibration earns or loses influence over long horizons.
- Regime-conditional calibration (trust weights per VIX regime, not global).
- Portfolio-level attribution: which agent's forecasts actually paid?
- Live paper-trading loop on the same governance stack.
