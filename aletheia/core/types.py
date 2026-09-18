"""Core value objects shared across the framework."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass(frozen=True)
class Bar:
    """One daily observation of an instrument."""
    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class MarketSnapshot:
    """Everything the committee sees for one rebalance date."""
    as_of: date
    bars: dict[str, list[Bar]]
    macro: dict[str, float]

    def closes(self, symbol: str) -> list[float]:
        return [b.close for b in self.bars.get(symbol, [])]

    def returns(self, symbol: str, window: int = 252) -> list[float]:
        px = self.closes(symbol)[-window - 1:]
        return [
            (px[i] / px[i - 1]) - 1.0
            for i in range(1, len(px))
            if px[i - 1] > 0
        ]


@dataclass(frozen=True)
class Forecast:
    """A scored, accountable forecast made by one committee member."""
    symbol: str
    horizon_days: int
    prob_up: float           # calibrated P(return > 0)
    expected_edge: float     # E[return] - risk-free, per horizon
    confidence: float        # agent's own confidence in [0, 1]
    rationale: str
    basis: dict[str, float]  # quantitative evidence behind the call
    issued_on: date
    agent: Optional[str] = None
    resolved_on: Optional[date] = None
    outcome: Optional[bool] = None
    brier: Optional[float] = None

    def with_resolution(self, resolved_on: date, outcome: bool) -> "Forecast":
        brier = (self.prob_up - (1.0 if outcome else 0.0)) ** 2
        return Forecast(
            symbol=self.symbol, horizon_days=self.horizon_days,
            prob_up=self.prob_up, expected_edge=self.expected_edge,
            confidence=self.confidence, rationale=self.rationale,
            basis=self.basis, issued_on=self.issued_on, agent=self.agent,
            resolved_on=resolved_on, outcome=outcome, brier=brier,
        )


@dataclass
class ThesisVerdict:
    """Result of a thesis surviving the adversarial gate."""
    thesis: str
    falsified: bool
    reasons: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)

    @property
    def survived(self) -> bool:
        return not self.falsified


def abstain_forecast(
    agent: Optional[str],
    snapshot: MarketSnapshot,
    symbol: str,
    horizon_days: int,
    why: str,
) -> "Forecast":
    """The one honest non-call: zero confidence, never graded, never fused.

    Shared by every committee member: an abstention is a first-class
    forecast record (it flows to the ledger and is visible in telemetry)
    but carries no probability content.
    """
    return Forecast(
        symbol=symbol, horizon_days=horizon_days,
        prob_up=0.5, expected_edge=0.0, confidence=0.0,
        rationale=f"abstain: {why}", basis={}, issued_on=snapshot.as_of,
        agent=agent,
    )


@dataclass(frozen=True)
class ResolutionRecord:
    """The graded outcome of one forecast, as it lands in the ledger.

    Single owner of the resolution payload shape: the Committee writes
    it, the skill book and observability read it. `from_payload` fails
    loudly (KeyError) if the ledger format drifts — a silent schema
    mismatch would otherwise corrupt skill statistics.
    """
    symbol: str
    agent: str
    prob_up: float
    outcome: bool
    confidence: float
    regime: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "agent": self.agent,
            "prob_up": round(self.prob_up, 4),
            "outcome": self.outcome,
            "confidence": round(self.confidence, 3),
            "regime": self.regime,
            # Skill base rates are about *decisions* (the judge's calls):
            # member forecasts are inputs, not decisions, so they are not
            # skill evidence.
            "skill_kind": "committee",
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ResolutionRecord":
        return cls(
            symbol=payload["symbol"],
            agent=payload["agent"],
            prob_up=payload["prob_up"],
            outcome=payload["outcome"],
            confidence=payload["confidence"],
            regime=payload["regime"],
        )
