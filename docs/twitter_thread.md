# Twitter thread — Aletheia launch

Twelve tweets, hook first, honest negatives in the middle, CTA at the end. Numbers all match the merged report (rounded to 3 decimals for readability; the exec summary carries full precision).

---

**1/**
We gave an LLM a seat on an investment committee and let the market grade it for 8 years.

390 predictions. Every one graded against what actually happened, net of costs.

Result: the rules beat it, but the machine grading it might be the real discovery.

A thread 🧵

**2/**
First, what we built. Not a trading bot — a REFEREE.

The problem with AI finance agents today: they're judged on how good their reports sound. Confidence wins. "Don't take big risks" is a prompt suggestion a model can argue past.

That's not accountability.

**3/**
The referee has four parts:

• A committee of forecasters (rules + any AI you seat)
• A trust model that grades every past call and sets voting weight
• A falsification gate — a bear agent whose job is to kill weak theses before money moves
• Hard risk law in CODE: position caps, drawdown brakes. No agent can override.

**4/**
The one rule that makes it all work:

Every member must commit to a falsifiable number BEFORE debate. "62% up over the next 21 sessions."

Then reality grades it. Net of trading costs — drift too small to trade doesn't count as being right.

**5/**
Now the experiment: one real AI model (gpt-oss:20b, open weights, running locally) vs four tiny hand-written rules. 390 graded forecasts over 8 years of the S&P.

Zero abstentions. Zero failures. Tamper-proof record of every call.

**6/**
What the AI was NOT: a market wizard.

Raw up/down score: 66.8% — identical to EVERY other member. Not skill: the S&P just rose on ~67% of windows in this era. Any forecaster leaning "up" lands there. The market giveth the base rate.

**7/**
The differentiation was confidence quality: when it said "70% sure," was it right 70% of the time?

All four rules beat it on accuracy (best Brier 0.236, worst 0.268; the AI: 0.270).

But on CALIBRATION the ordering flipped: the AI (ECE 0.146) knew what it didn't know better than the quant rule that narrowly beat it (0.182).

**8/**
Final rank: LAST of five.

Honest headline: a current-gen AI predicts markets about as well as — but no better than — simple rules a person writes in an afternoon.

And the full system isn't an alpha engine either. It does NOT beat a boring index fund on risk-adjusted return. Published, prominently.

**9/**
More honesty: our pattern-finding "skills" feature helped in backtest (3 of 3 markets) — and exactly 0.0pp out-of-sample.

Our own instrumentation caught us fooling ourselves. That's what it's built for.

**10/**
What DID generalize is safety:

28 years of Japanese stocks, including an 82% crash the market never recovered from.

Index: −41.2%, 81.8% max drawdown.
Governed committee: +7.7%, 6.5% max drawdown.

**11/**
But the trust machinery did its job perfectly:

Trust 1.0 → 1.407 (promoted above its prior). Demoted through its bad stretch (2021–24 bear). Allowed to recover (2024–26).

No worship, no exile. Influence rising and falling with measured performance.

**12/**
Everything's open: stdlib-only Python, 51 tests in CI, every number traceable to a hash-chained ledger you can verify yourself.

The referee is the result. The forecaster can be anyone — including you.

Repo + technical report:
https://github.com/j-poc/aletheia-framework
