# Aletheia: Market-Graded Governance for LLM Investment Committees

**Status:** research prototype. The market matrix can be rerun from the exact
inputs identified in [`data/source_manifest.json`](../data/source_manifest.json).
Those source files are not distributed here. The local LLM study below is
archived and has not been rerun on the current engine.

## The problem

An investment committee needs a record of what each forecaster believed before
the outcome was known. It also needs rules that execute when a recommendation
breaches risk limits. Aletheia tests whether those records and rules can be
built into an agent committee and audited after the fact.

## The system, in one paragraph

Aletheia records and grades probabilistic forecasts, changes member weights based
on past Brier scores, checks theses with a bear agent, and enforces position and
drawdown rules in code. A hash-linked ledger records decisions and outcomes. It
detects altered entries if its original head hash is retained separately. Market
observations are clipped to the decision date; historical FRED publication
vintages are not stored, so full knowledge-time correctness is not established.

## The grading contract

Every member records a falsifiable probability (for example, "62% up over 21
sessions") before the outcome. Later, the market grades it: a call counts as
correct only if the realized move exceeded the assumed round-trip cost (10 bps).
Member weights then change according to absolute historical Brier scores. The
weights do not require a member to beat a simple forecast baseline.

## Headline findings, including the ones against us

**1. The backtests have low drawdown, with lower exposure.** On the active
late-2018 to August-2026 windows, the full system returned +25.7%, +6.3%, and +10.2%
on the S&P 500 plus Nasdaq Composite, Dow, and Nikkei. Maximum drawdown was 5.5%,
3.6%, and 5.9%. A simple initial 25% index / 75% cash portfolio had higher returns,
higher Sharpe, and higher drawdowns in all three. The lower drawdowns do not isolate
the benefit of the risk rules from the effect of holding less market exposure.

**2. No investment edge is established.** The full system loses to that simple
baseline on Sharpe in all three recent markets. Its stationary-bootstrap 95%
Sharpe intervals are [0.04, 1.32], [-0.18, 1.03], and [-0.23, 1.21].

**3. The current trust rule is not evidence of forecasting skill.** In the
S&P 500 plus Nasdaq run, the fused decisions scored 0.2439 and 0.2636 Brier,
respectively. A rolling base-rate forecast using only outcomes resolved by each
decision date scored 0.2322 and 0.2431 on the same calls. All three individual
members also scored worse than that comparator in both markets. Their weights
still rose under the current absolute-score rule.

**4. Skills are estimated conservatively.** Only the committee's fused
decisions contribute, and each forecast uses the market regime known when it
was issued. Skills add 2.5 percentage points on the U.S. pair, subtract 0.6 on
Dow, add 0.6 on Nikkei, and add nothing in the 1990–2017 Nikkei window.

**5. The archived LLM experiment establishes member grading, with a boundary.** A
local `gpt-oss:20b` member made 390 forecasts; 385 resolved, with no abstentions or
retries. Its archived Brier score was 0.2701 and ECE was 0.1458. That result shows
the contract can grade a real model over a long history. The experiment ran on the
old engine, so its committee ranking and portfolio outcomes are not current claims.

## Why this research matters

The implementation demonstrates a record and scoring path for machine forecasts,
plus executable risk limits. The negative baseline result shows why scoring alone
is insufficient: a member can gain weight without outperforming a simple forecast.
The next experiment is to make influence conditional on baseline-relative skill
and test whether that improves decisions across markets and periods.

## What we would want from a collaboration

Independent review of the grading and market-data vintages; an exposure-matched
risk comparison; a baseline-relative trust rule; and a rerun of the archived LLM
experiment on the current engine.
The [technical report](TECHNICAL_REPORT.md) gives the full matrix and limitations.
