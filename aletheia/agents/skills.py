"""Regime skills: recurring plays distilled from the committee's own ledger.

Andrew Qu's Vercel talk describes a recurring job that distills thousands
of past agent queries into reusable "skills" so every new run starts with
accumulated context instead of from nothing. Aletheia's analog: a
recurring job that distills the committee's *resolved decisions* into
regime-conditional base rates.

Design constraints (diverging from the talk where the domain demands it):

* **Walk-forward only.** Skills are rebuilt from the ledger's resolutions
  at each decision day; every resolution reflects an outcome fully known
  by that day (the forecast was issued H sessions earlier). No future
  information can enter, by construction.
* **Shrunk to the committee prior.** A regime skill fires only when its
  shrunk hit rate clears the decision bar; small samples can never push
  it over. This is the governance layer the Vercel story lacked — their
  skills inherit an agent's credibility, ours must earn it.
* **Ledger-native.** Skills are computed from ledger entries, so the
  skill book is auditable: you can replay exactly how any skill was
  learned.
* **About decisions.** Skill base rates cover the committee's calls only
  (the judge's fused forecasts). Member forecasts are inputs to a
  decision, not decisions — grading them into the skill book would
  double-count the same outcome.

A skill key: (regime, prob_bucket), e.g. ("calm", "hi") -> shrunk
net-of-cost hit rate of committee calls with P(up) in [0.6, 1.0) made in
calm regimes.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Optional

from aletheia.core.types import MarketSnapshot, ResolutionRecord

BUCKET_OF = {"lo": (0.0, 0.4), "mid": (0.4, 0.6), "hi": (0.6, 1.01)}


def regime_of(snapshot: MarketSnapshot, symbol: str) -> str:
    """Volatility regime from the symbol's own recent history."""
    rets = snapshot.returns(symbol, 63)
    if len(rets) < 20:
        return "unknown"
    vol = statistics.pstdev(rets) * math.sqrt(252)
    if vol < 0.15:
        return "calm"
    if vol < 0.30:
        return "normal"
    return "stressed"


def prob_bucket_of(prob_up: float) -> str:
    if prob_up < 0.4:
        return "lo"
    if prob_up < 0.6:
        return "mid"
    return "hi"


@dataclass
class SkillStats:
    regime: str
    bucket: str
    n: int = 0
    hits: int = 0

    def shrunk_hit_rate(self, prior: float, k: float) -> float:
        if self.n == 0:
            return prior
        return (self.hits + prior * k) / (self.n + k)


class RegimeSkillBook:
    """Recurring-play base rates, learned only from resolved history."""

    def __init__(
        self,
        decision_bar: float = 0.56,
        prior: float = 0.50,
        shrinkage_n: int = 30,
        min_gap: float = 0.02,
        max_shift: float = 0.08,
    ) -> None:
        self.decision_bar = decision_bar
        self.prior = prior
        self.k = shrinkage_n
        self.min_gap = min_gap
        self.max_shift = max_shift
        self.stats: dict[tuple[str, str], SkillStats] = {}
        self.last_distilled_on: Optional[date] = None

    # ------------------------------------------------------------------
    def distill(self, ledger) -> int:
        """Rebuild skill stats from all resolutions in the ledger.

        Called at each decision day (after the day's resolutions have been
        appended). Rebuilding from the full ledger is idempotent and keeps
        the skill book exactly consistent with the auditable record.
        """
        for st in self.stats.values():
            st.n = 0
            st.hits = 0
        count = 0
        for e in ledger.entries:
            if e.kind != "resolution":
                continue
            rec = ResolutionRecord.from_payload(e.payload)
            if rec.confidence <= 0:
                continue  # abstentions are never skill evidence
            key = (rec.regime, prob_bucket_of(rec.prob_up))
            st = self.stats.setdefault(
                key, SkillStats(regime=key[0], bucket=key[1])
            )
            st.n += 1
            if rec.outcome:
                st.hits += 1
            count += 1
        return count

    def recall(
        self,
        snapshot: MarketSnapshot,
        symbol: str,
        prob_up: float,
    ) -> Optional[dict]:
        """Recurring-play recall: does this (regime, bucket) historically clear the bar?"""
        regime = regime_of(snapshot, symbol)
        bucket = prob_bucket_of(prob_up)
        st = self.stats.get((regime, bucket))
        if st is None or st.n == 0:
            return None
        rate = st.shrunk_hit_rate(self.prior, self.k)
        if rate < self.decision_bar + self.min_gap:
            return None
        shift = (rate - self.prior) * (self.k / (self.k + st.n))
        shift = max(0.0, min(self.max_shift, shift))
        return {
            "regime": regime,
            "bucket": bucket,
            "n": st.n,
            "shrunk_hit_rate": round(rate, 4),
            "suggested_shift": round(shift, 4),
        }

    def to_ledger_payload(self) -> dict:
        live = {k: v for k, v in self.stats.items() if v.n > 0}
        return {
            "n_skills": len(live),
            "total_observations": sum(v.n for v in live.values()),
            "top": [
                {
                    "regime": k[0], "bucket": k[1],
                    "n": v.n, "hits": v.hits,
                    "shrunk_hit_rate": round(v.shrunk_hit_rate(self.prior, self.k), 4),
                }
                for k, v in sorted(live.items(), key=lambda kv: -kv[1].n)[:10]
            ],
        }
