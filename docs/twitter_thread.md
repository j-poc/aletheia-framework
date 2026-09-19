# Twitter thread, Aletheia launch

Revised research draft, September 19. The earlier LLM experiment is archived;
current market numbers below come from the corrected engine.

---

**1/**
We built an investment committee that grades its own forecasts against market outcomes.

Then we found two errors in our backtest and reran the evidence. The corrected result
is more useful than the original headline.

A thread 🧵

**2/**
First, what we built. Not a trading bot, a REFEREE.

The problem with AI finance agents today: they're judged on how good their reports sound. Confidence wins. "Don't take big risks" is a prompt suggestion a model can argue past.

That's not accountability.

**3/**
The referee has four parts:

• A committee of forecasters (rules + any AI)
• A trust model: grades calls, sets voting weight
• A falsification gate: a bear agent kills weak theses before money moves
• Risk law in CODE: caps, leverage, drawdown brakes. No agent overrides.

**4/**
The one rule that makes it all work:

Every member must commit to a falsifiable number BEFORE debate. "62% up over the next 21 sessions."

Then reality grades it. Net of trading costs, drift too small to trade doesn't count as being right.

**5/**
An earlier local experiment seated gpt-oss:20b on the S&P. It made 390 forecasts;
385 resolved, with no abstentions or retries. That archived member-calibration result
has not been rerun through the corrected committee.

**6/**
The model's archived Brier score was 0.2701. That tells us the member contract can
grade a real model over years. It does not establish predictive edge or a current
committee ranking.

**7/**
The first bug dropped a held position's price move on rebalance days. We now mark
the old holdings before placing a new order, and held weights drift with prices.

**8/**
The second bug taught the skill book from every member forecast and used the market
regime when each forecast resolved. It now learns only from the fused decision and
the regime known when the call was made.

**9/**
Corrected skills: +2.5 percentage points on the S&P plus Nasdaq Composite,
-0.6 on Dow, +0.6 on Nikkei, and 0.0 in the 1990–2017 Nikkei window.
The prior 73% skill cell is invalid.

**10/**
Across the three recent markets, full-system maximum drawdown was 3.6% to 5.9%.
An initial 25% index / 75% cash baseline drew down 10.2% to 12.1%.
The system also earned less and had lower Sharpe in every market.

**11/**
Low drawdown by itself does not prove the risk rules added value. The strategy often
held less market exposure. An exposure-matched comparison is still needed.

**12/**
The corrected build has 58 passing tests and an independently replayed portfolio
ledger. Every member in the U.S. pair also lagged a rolling base-rate forecast on
Brier score. The result is a working research instrument with unproven investment
advantage. The raw market inputs are not distributed; the report pins their hashes.

Repo + technical report:
https://github.com/j-poc/aletheia-framework
