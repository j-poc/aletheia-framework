"""Adversarial falsification gate.

A thesis is not "debated" — it is attacked. The gate consumes the bear's
falsification pressure and the quant's corroboration and returns a binary
verdict: does the thesis deserve capital? The RiskGovernor blocks entries
for any symbol whose thesis fails this gate (Art. III of the constitution).
"""
from __future__ import annotations

from typing import Optional

from aletheia.core.types import Forecast, MarketSnapshot, ThesisVerdict


class FalsificationGate:
    """Binary thesis verdict from adversarial evidence.

    A thesis survives only if the bear's P(down) stays under the bar AND
    the quant's directional edge is not actively contradicting it. The
    bar tightens as bear pressure rises — strong falsifiers face a
    stricter standard, by construction.
    """

    def __init__(self, base_bar: float = 0.60, stress_bar: float = 0.50,
                 contradict_slack: float = -0.02) -> None:
        self.base_bar = base_bar      # falsify above this outright
        self.stress_bar = stress_bar  # falsify above this IF evidence corroborates
        self.contradict_slack = contradict_slack

    def judge(
        self,
        thesis: str,
        symbol: str,
        bear: Optional[Forecast],
        quant: Optional[Forecast],
        snapshot: Optional[MarketSnapshot] = None,
    ) -> ThesisVerdict:
        reasons: list[str] = []
        citations: list[str] = []

        if bear is None or bear.confidence <= 0.0:
            return ThesisVerdict(
                thesis=thesis, falsified=True,
                reasons=["no active falsifier — thesis untested, therefore rejected"],
            )

        bear_pdown = 1.0 - bear.prob_up

        # independent evidence: does momentum actively contradict the thesis?
        contradiction: Optional[str] = None
        if quant is not None and quant.confidence > 0.2:
            edge_z = quant.basis.get("edge_z", 0.0)
            if edge_z < self.contradict_slack:
                contradiction = f"quant momentum edge contradicts thesis (edge_z {edge_z:+.2f})"

        if bear_pdown >= self.base_bar:
            reasons.append(
                f"bear P(down) {bear_pdown:.0%} >= falsification bar {self.base_bar:.0%} "
                f"(vol {bear.basis.get('vol_annualized', 0):.0%}, "
                f"drawdown {bear.basis.get('drawdown', 0):.0%}, "
                f"crash freq {bear.basis.get('crash_frequency', 0):.0%})"
            )
            citations.append("bear.falsification_pressure")
        elif bear_pdown >= self.stress_bar and contradiction:
            reasons.append(
                f"bear P(down) {bear_pdown:.0%} >= stress bar {self.stress_bar:.0%} "
                "with corroborating contradiction"
            )
            citations.append("bear.stress_pressure")

        if contradiction:
            reasons.append(contradiction)
            citations.append("quant.momentum_contradiction")

        falsified = len(reasons) > 0
        if not falsified:
            reasons.append(
                f"survived: bear P(down) {bear_pdown:.0%} below bars, "
                "no contradictory quant evidence"
            )
        return ThesisVerdict(
            thesis=thesis, falsified=falsified,
            reasons=reasons, citations=citations,
        )
