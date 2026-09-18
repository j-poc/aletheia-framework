"""CommitteeContext: the judge sees everything, not a summary.

The "one agent with all the mega context" lesson: chained specialists
degrade because each stage only receives a summary of the last. Aletheia's
judge is the decision-maker, so it gets the *complete* picture every
decision: every member's full forecast (numbers and stated evidence), the
macro state, the volatility regime, conviction across the whole book, and
any recurring-play (skill) recall — fused with bounded, logged adjustments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from aletheia.core.types import Forecast

# The judge may never move its probability more than this much on context
# alone — the members' evidence, not the context, dominates every call.
MAX_CONTEXT_SHIFT = 0.10


@dataclass
class CommitteeContext:
    as_of: date
    symbol: str
    macro: dict[str, float] = field(default_factory=dict)
    regime: str = "unknown"
    members: list[Forecast] = field(default_factory=list)
    trust_weights: dict[str, float] = field(default_factory=dict)
    cross_symbol: dict[str, float] = field(default_factory=dict)  # sym -> fused p
    skill: Optional[dict] = None  # RegimeSkillBook.recall() result

    @property
    def vix(self) -> Optional[float]:
        return self.macro.get("VIX")

    @property
    def curve_slope(self) -> Optional[float]:
        """10y minus 2y Treasury yield, in percentage points."""
        if "UST10Y" in self.macro and "UST2Y" in self.macro:
            return self.macro["UST10Y"] - self.macro["UST2Y"]
        return None
