# Aletheia: Market-Graded Governance for LLM Investment Committees

**Executive Summary** · Full report: `docs/TECHNICAL_REPORT.md` · Status: research prototype, stdlib-only, 51-test CI, all numbers reproducible from hash-chained ledgers.

## The problem

Multi-agent LLM systems for financial decision-making are evaluated by output quality — benchmark passes, report readability — not by whether their probabilistic claims resolve. Influence inside such systems is asserted by prompt role ("you are the senior analyst"), not earned by track record; risk limits are prose instructions a confident model can argue past. When real capital is at stake, none of this is accountability.

## The system, in one paragraph

Aletheia is not a trading strategy — it is a **referee, a rulebook, and a record-keeper** sitting above any forecaster, whether a hand-written rule or a frontier model. The *committee* (four small deterministic agents, plus any seated LLM) makes the forecasts. The *trust model* grades every past forecast against realized outcomes and sets each member's voting weight accordingly. The *falsification gate* forces a dedicated bear agent to attack every thesis before capital moves. The *constitution* executes seven hard risk articles in code between every proposal and every order, vetoing anything — no agent can override it, and every veto is named and logged. The *ledger* records all of it in a hash-chained, tamper-evident transcript. The stack is stdlib-only Python, deterministic to the byte, and walks forward strictly (point-in-time data; no member can see the future).

## The grading contract

Every member must commit to a **pre-registered, falsifiable probability** ("62% up over 21 sessions") before evidence review. Later, the market grades it: a call counts as correct only if the realized move exceeded the round-trip cost (10 bps). Three consequences: influence is earned, not assigned (confidently wrong members are demoted automatically); risk law is code, not prose; and every decision is receipt-backed.

## Headline findings — including the ones against us

**1. The risk layer works, and it generalizes.** Across three equity markets (S&P 500+Nasdaq, Dow, Nikkei; Sep 2018–Aug 2026), the committee contains maximum drawdown to **2.4–5.7%** through COVID-19 and the 2022 bear — versus 10–11% for a matched fixed-mix baseline and 31–37% for buy-and-hold. Out-of-window, on 28 years of Nikkei (1990–2017) spanning Japan's post-bubble collapse, the governed book returned **+7.7% with 6.5% max drawdown while the index lost −41.2% with an 81.8% drawdown**. Containment, not alpha, is the reproducible result.

**2. The system is not an alpha engine.** It beats trivial baselines on Sharpe in only 1 of 3 markets (bootstrap 95% CIs overlap zero in two of three: [0.06, 1.30], [0.16, 1.38]). We publish this prominently: anyone evaluating the framework as a money-maker should stop reading here.

**3. A component that looked like edge was regime-fit.** Shrinkage-gated regime skills improved returns in 3 of 3 in-window markets — and contributed exactly **0.0pp out-of-window**. Decomposition showed the skill book's celebrated cell (73.1% hit rate, n=1071) carried no bucket-level predictive power at all. The architecture's own instrumentation caught its own authors' optimistic read, which is the point of the architecture.

**4. What an eight-year LLM grading study does — and does not — show.** We seated a current-generation open-weights 20B reasoning model (`gpt-oss:20b`, local, `reasoning_effort: low`) through the standard member contract: 390 pre-registered forecasts (385 resolved for grading), **0 abstentions, 0 retries**, all graded net-of-cost, with the resulting 5,044-entry ledger verified end-to-end.

What it does **not** show is that LLMs predict markets especially well. The model finished **last of five** members. Its raw directional score was identical to everyone else's — 66.8% — because the S&P rose on ~67% of graded windows in this era, so any forecaster leaning "up" at reasonable confidence lands there; raw up/down score was saturated. The differentiation lived in *confidence quality*: all four hand-written rules out-graded the model on accuracy — three decisively (bull 0.2364, bear 0.2393, judge 0.2482 Brier) and the momentum/volatility quant agent narrowly (0.2684 vs 0.2701). On one measure the ordering reversed: **calibration**. The model was better calibrated than the quant rule that beat it (ECE 0.146 vs 0.182) — it "knew what it didn't know" better than the rule that scored more accurate — even while carrying the worst Brier on the committee.

What it **does** show is that the governance machinery works on a real, current AI: the committee **promoted the model above its prior** (trust 1.0 → 1.407; above prior in 374/390 decisions, dipping to 0.863, peaking at 1.473) and priced its trajectory — per-third Brier **0.2621 → 0.2977 → 0.2508**, degradation concentrated in the 2021–2024 bear, recovery priced through 2024–2026. Demoted through the bad regime, never discarded. To our knowledge this is the first publicly documented market-graded, multi-year calibration record for an LLM forecaster under earned-influence governance. It is one model, one market, graded under the committee's own rule — the frontier-API and multi-model extensions are open, and the contract exists to run them.

**The study's overall result is therefore the referee, not any forecaster:** a complete, minimal, reproducible instrument that grades AI claims against reality, makes influence follow the scorecard, enforces hard risk law opinion cannot argue past, and keeps tamper-evident receipts — demonstrated end-to-end over years, on a real LLM, with its own negatives published next to its wins.

## Why labs should care

The hard problem in agentic AI is not making agents capable; it is making their claims checkable and their influence contingent on being right. Markets are merely the grader we wired first — relentless, quantitative, immune to persuasion. The same discipline applies wherever an AI's probabilistic claims resolve later: any checkable ground truth will do.

## What we would want from a collaboration

Independent review of the grading and walk-forward machinery (the ledger makes this cheap); extension of the LLM study to frontier-API models and additional markets, including head-to-head model comparison; longer histories and sub-period stability analysis. The repo runs the full evaluation from a warm cache in ~15 seconds.
