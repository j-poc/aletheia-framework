# Aletheia: Market-Graded Governance for LLM Investment Committees

**Executive Summary** · Full report: `docs/TECHNICAL_REPORT.md` · Status: research prototype, stdlib-only, 51-test CI, all numbers reproducible from hash-chained ledgers.

## The problem

Multi-agent LLM systems for financial decision-making are evaluated by output quality — benchmark passes, report readability — not by whether their probabilistic claims resolve. Influence inside such systems is asserted by prompt role ("you are the senior analyst"), not earned by track record; risk limits are prose instructions a confident model can argue past. When real capital is at stake, none of this is accountability. Aletheia is a governance layer that inverts all three defaults.

## The mechanism

Every committee member — hand-built heuristic or LLM — must emit **pre-registered, probabilistic forecasts** ("62% up over 21 sessions") committed before evidence review, which are later graded against realized market outcomes **net of trading costs** (10 bps round trip). Three consequences fall out of that grading:

1. **Influence is earned, not assigned.** Trust weights derive from calibration track record (Brier, ECE) with Bayesian shrinkage; confidently wrong members are demoted automatically, and a dedicated falsifier must fail to kill a thesis before capital moves.
2. **Risk law executes in code.** Seven constitutional articles (position caps, leverage, VaR, drawdown circuit breaker) run between every proposal and every order; every veto is named and logged; no agent — however calibrated — can override.
3. **Every decision is receipt-backed.** Forecasts, vetoes, and resolutions land in a hash-chained, tamper-evident ledger; observability is replay.

The stack is stdlib-only Python, deterministic to the byte, and walks forward strictly (point-in-time data; no member, human or model, can see the future).

## Headline findings — including the ones against us

**1. The risk layer works, and it generalizes.** Across three equity markets (S&P 500+Nasdaq, Dow, Nikkei; Sep 2018–Aug 2026), the committee contains maximum drawdown to **2.4–5.7%** through COVID-19 and the 2022 bear — versus 10–11% for a matched fixed-mix baseline and 31–37% for buy-and-hold. Out-of-window, on 28 years of Nikkei (1990–2017) spanning Japan's post-bubble collapse, the governed book returned **+7.7% with 6.5% max drawdown while the index lost −41.2% with an 81.8% drawdown**. Containment, not alpha, is the reproducible result.

**2. The system is not an alpha engine.** It beats trivial baselines on Sharpe in only 1 of 3 markets (bootstrap 95% CIs overlap zero in two of three: [0.06, 1.30], [0.16, 1.38]). We publish this prominently: anyone evaluating the framework as a money-maker should stop reading here.

**3. A component that looked like edge was regime-fit.** Shrinkage-gated regime skills improved returns in 3 of 3 in-window markets — and contributed exactly **0.0pp out-of-window**. Decomposition showed the skill book's celebrated cell (73.1% hit rate, n=1071) carried no bucket-level predictive power at all; the mechanism works as a deployment filter, not a probability refiner. The architecture's own instrumentation caught its own authors' optimistic read, which is the point of the architecture.

**4. An LLM graded by the market for eight years: earns a seat, loses the top spot.** We seated a current-generation open-weights 20B reasoning model (`gpt-oss:20b`, local, `reasoning_effort: low`) through the standard member contract: 390 pre-registered forecasts across the full window, **0 abstentions, 0 retries**, every call graded net-of-cost. The committee **promoted it above its prior** (trust 1.0 → 1.407; above prior in 374/390 decisions) while every specialized heuristic out-graded it — final rank 5 of 5 (Brier 0.2701 vs the bull agent's 0.2364; ECE 0.146, better than the quant member's 0.182). Its per-third Brier arc — **0.2621 → 0.2977 → 0.2508** — shows degradation concentrated in the 2021–2024 bear and recovery in 2024–2026: the trust mechanism demoted through the bad regime, never discarded, and priced the recovery. To our knowledge this is the first publicly documented market-graded, multi-year calibration record for an LLM forecaster under earned-influence governance. It is one model, one market, graded under the committee's own rule — the frontier-API extension is open and the contract exists to run it.

## Why labs should care

The hard problem in agentic AI is not making agents capable; it is making their claims checkable and their influence contingent on being right. Aletheia contributes a complete, minimal, reproducible instrument for exactly that: a grading contract any forecaster can sit, an influence mechanism that reality controls, hard risk law that opinion cannot argue past, and an audit ledger that makes every claim mechanically verifiable. Markets are merely the grader we wired first — relentless, quantitative, immune to persuasion. The same discipline applies wherever an AI's probabilistic claims resolve later: any checkable ground truth will do.

## What we would want from a collaboration

Independent review of the grading and walk-forward machinery (the ledger makes this cheap); extension of the LLM study to frontier-API models and additional markets; longer histories and sub-period stability analysis. The repo runs the full evaluation from a warm cache in ~15 seconds.
