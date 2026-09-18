# Aletheia

**A calibration-governed AI investment framework.**

Most "AI investing" stacks today — including the multi-agent research patterns emerging from
the major labs — share one architecture: capable models research a market, debate, and
produce a recommendation. The missing layer is *governance*: nothing tracks whether the
models were actually right, nothing lets them earn or lose influence, and nothing structurally
prevents a confident model from taking excessive risk.

Aletheia is that missing layer, built as a complete decision engine:

| Mechanism | What it does | Where |
|---|---|---|
| **Calibration-trust committee** | Every agent emits a *gradeable probabilistic forecast*. Outcomes are scored (Brier, log score, ECE) and each agent's voting weight is its earned track record, shrunk toward the prior while samples are small. Agents that are confidently wrong get demoted — automatically. The judge fuses member votes with a **bounded mega-context** (macro state, regime, cross-symbol conviction, skill recall; ≤10pp total shift, every adjustment logged). | `aletheia/calibration/trust.py`, `aletheia/agents/committee.py`, `aletheia/agents/context.py` |
| **Adversarial falsification gate** | A dedicated bear agent exists to *kill* theses, not to balance debate. A thesis only reaches capital if it survives: bear pressure below the bar AND no contradictory quant momentum evidence. | `aletheia/agents/gate.py` |
| **Constitutional risk layer** | Seven articles of hard risk law — position caps, leverage cap, falsification gate, drawdown circuit breaker (enforced **daily**, not just at rebalance), cooldown, daily VaR cap, and a drawdown-budget scaler. Enforced in code on the order pipeline; no agent can argue past it, and every veto is logged. | `aletheia/core/constitution.py` |
| **Tamper-evident decision ledger** | Every forecast, thesis, veto, order and resolution is hash-chained (sha256, prev-hash linked) into an append-only JSONL ledger. Rewrite history and `verify()` breaks. | `aletheia/calibration/ledger.py` |
| **Walk-forward governance engine** | The `Committee` owns the decision cycle (members, gate, judge fusion, skill recall); the engine owns execution: sizing, constitutional enforcement every session, order/cost simulation, and forecast grading. Point-in-time data, no look-ahead, deterministic reruns. | `aletheia/engine/backtest.py` |
| **Regime skill book** | A recurring job distills the ledger's *resolved committee decisions* into regime-conditional base rates ("calm regime + high-confidence call → 73% net-of-cost hit rate"). Recalled walk-forward-only, shrunk to the prior, and every application is logged. | `aletheia/agents/skills.py` |
| **Ledger-native observability** | Trust-weight evolution, veto breakdown by article, and the live skill book — all replayed from the hash-chained ledger itself, not a parallel telemetry pipeline. | `aletheia/observability.py` |

```
                      ┌──────────────────────────────────────┐
                      │            DataProvider              │
                      │   FRED (real, keyless) / Synthetic   │
                      └──────────────┬───────────────────────┘
                                     │ point-in-time snapshot
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
python3 -m aletheia.cli backtest --ledger-out run_ledger.jsonl

# offline, fully reproducible synthetic market
python3 -m aletheia.cli backtest --synthetic --seed 7

# ablation: what each governance layer is worth
python3 -m aletheia.cli ablation --synthetic

# verify a decision ledger's integrity
python3 -m aletheia.cli verify-ledger --path run_ledger.jsonl

# observability report, replayed from the ledger
python3 -m aletheia.cli report --path run_ledger.jsonl

# run the test suite
python3 -m pytest tests/ -q
```

Runs are **deterministic**: same data + same seed → an identical report, byte for byte
(verified by running the engine twice in-process). The ledger's *content* — every
sequence, kind, payload, and hash chain — is deterministic too; only the wall-clock
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

All numbers below are reproducible today with the quickstart commands on a warm FRED cache
(`--start 2018-09-01 --end 2026-08-31`), deterministic to the last byte.

**Real data (FRED, S&P 500 + Nasdaq, Sep 2018 – Aug 2026), full system:**
**+21.5% total return, Sharpe 0.66, max drawdown 5.7%** (constitution limit: 15% — never
breached, including through the 2020 crash and the 2022 bear). 390 committee decisions,
500 vetoes, 8,328 ledger entries, 3,080 graded forecasts, 59.4% directional hit rate,
mean Brier 0.2547.

**Grading is net of trading costs**: a forecast only counts as right if the move exceeded
the round-trip cost of acting on it — agents earn credit for tradable edge, not epsilon
drift. The regime skill book fired 539 times; its strongest skill learned "calm regime,
high-confidence call: 783/1071 = 73% net-of-cost hit rate."

**The performance ladder** (one lever removed at a time; `EngineConfig` toggles):

```
V4 full: skills + macro + context     ret +21.46%  sharpe 0.66  maxDD 5.69%  vetoes 500
  − context (judge sees only members) ret +23.37%  sharpe 0.70  maxDD 5.79%  vetoes 522
  − macro (agents blind to VIX/curve) ret +24.73%  sharpe 0.71  maxDD 6.36%  vetoes 543
  − skills (no recurring plays)       ret +20.47%  sharpe 0.64  maxDD 5.48%  vetoes 452
V3 baseline (no recipe levers)        ret +22.60%  sharpe 0.67  maxDD 5.93%  vetoes 503
```

Honest reading (one market history is n=1 — re-run the ladder per period before deciding):

* **Skills are the consistent winner** (+1.0pp here, the top performer in every ladder we
  have run): accumulated, shrinkage-gated recurring plays pay.
* **Macro knowledge buys tail protection, not return**: VIX-aware bears and curve-aware
  bulls gave up ~3.3pp of return for ~0.7pp less max drawdown. Whether that trade is right
  depends on your risk budget, not your backtest.
* **The mega-context judge pass costs ~1.9pp on this path** — kept in place because it is
  bounded (≤10pp), auditable (every adjustment in the ledger), and one path is n=1. Every
  lever is a toggle; publish what the grader says, not what the design hoped.

**Synthetic (regime-switching GBM):** near-flat returns by design — the market has almost
no exploitable edge, and a well-governed committee *should* refuse to bleed. Ablations show
the constitution is what contains tail risk (max DD 2.8% → 5.2% when disabled).

Read: Aletheia optimizes *decision quality per unit of risk*, not headline return. The
calibration ledger is the product — the equity curve is a byproduct.

## Best-performing agents: the applied recipe

Applying the production-agent performance recipe (mega-context over chained
summaries; whole-domain knowledge over narrow feeds; skills at run start) to
Aletheia produced three mechanisms — and, more importantly, the **measured
performance ladder** above, reproduced warm and published verbatim, including
the levers that didn't pay.

## Lessons applied (from building agents in production)

Several design choices deliberately incorporate — or diverge from — hard-won lessons
from production agent building (e.g. Vercel's data-science-agent journey):

1. **Evals can lie.** Vercel's agent aced 30 internal evals and still failed real users.
   Aletheia's grader is the market itself, and grading is *net of trading costs* — the
   eval cannot be gamed by epsilon drift or curated benchmarks. Synthetic runs are
   treated as smoke tests, never as evidence of edge.
2. **Skills from history — but governed.** Their recurring job distills past queries into
   skills so agents don't start from nothing. Aletheia distills *resolved decisions* into
   regime base rates — but skills must clear the decision bar through shrinkage, fire
   only on walk-forward data, and log every application to the ledger. Accumulated
   context without an earned-credibility layer inherits an agent's biases; ours doesn't.
3. **Observability is replay, not extra plumbing.** One append-only event log serves as
   audit trail, training data for skills, and the source for all reporting.
4. **Filesystem > bespoke pipelines.** Where an agent in this stack needs breadth
   (future LLM members), the plan is minimal primitives — read/write/execute in a
   data sandbox — not prescriptive hand-mapped tool chains.

## Data

`FredProvider` pulls official keyless daily data from the St. Louis Fed (S&P 500, Nasdaq
Composite, VIX, 2y/10y Treasury) with a disk cache. Yahoo Finance was rate-limiting (HTTP
429) this environment, and Stooq is bot-walled — FRED is the robust keyless choice. To plug
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

- **LLM committee members**: the `Agent` ABC + `Forecast` contract are exactly the interface
  a frontier-LLM agent needs — its reasoning becomes *pre-registered, gradeable, and
  trust-weighted* like any other member. Weak LLMs get demoted by the same math.
- Regime-conditional calibration (trust weights per VIX regime, not global).
- Portfolio-level attribution: which agent's forecasts actually paid?
- Live paper-trading loop on the same governance stack.
