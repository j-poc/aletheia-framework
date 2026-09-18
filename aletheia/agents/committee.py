"""The committee: quantitative, adversarial, and judging agents.

Every agent produces a *scored forecast* — not a vibe, not a paragraph of
convincing prose — which is exactly what makes them gradeable and the
committee trustworthy. The bear agent exists to falsify, not to balance.

`Committee` is the single owner of the decision cycle: it convenes the
members, runs the falsification gate, performs both judge fusion passes
(base trust-weighted, then mega-context), applies skill recall, and writes
every decision artifact to the ledger. The engine consumes its output and
owns only execution (sizing, risk, orders, grading).
"""
from __future__ import annotations

import math
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from aletheia.agents.context import CommitteeContext, MAX_CONTEXT_SHIFT
from aletheia.agents.gate import FalsificationGate
from aletheia.agents.skills import RegimeSkillBook
from aletheia.calibration.ledger import DecisionLedger
from aletheia.core.types import Forecast, MarketSnapshot, ThesisVerdict


class Agent(ABC):
    """A committee member that emits gradeable probabilistic forecasts."""

    def __init__(self, name: str, horizon_days: int = 21) -> None:
        self.name = name
        self.horizon_days = horizon_days
        self._last_issued: Optional[Forecast] = None

    @abstractmethod
    def forecast(self, snapshot: MarketSnapshot, symbol: str) -> Forecast:
        ...

    def pre_register(self, f: Forecast) -> Forecast:
        """Pin the forecast before evidence review (pre-registration)."""
        self._last_issued = f
        return f


def _abstain(name: Optional[str], snapshot: MarketSnapshot, symbol: str,
             horizon_days: int, why: str) -> Forecast:
    return Forecast(
        symbol=symbol, horizon_days=horizon_days,
        prob_up=0.5, expected_edge=0.0, confidence=0.0,
        rationale=f"abstain: {why}", basis={}, issued_on=snapshot.as_of,
        agent=name,
    )


class QuantAgent(Agent):
    """Momentum + volatility-regime signals, honestly quantified.

    Produces a probability of upward drift over the horizon from
    normalized momentum, discounted by realized-vol regime.
    """

    def __init__(self, momentum_window: int = 63, horizon_days: int = 21) -> None:
        super().__init__("quant", horizon_days)
        self.momentum_window = momentum_window

    def forecast(self, snapshot: MarketSnapshot, symbol: str) -> Forecast:
        rets = snapshot.returns(symbol, window=252)
        if len(rets) < self.momentum_window + 5:
            return _abstain(self.name, snapshot, symbol,
                            self.horizon_days, "insufficient history")

        window = rets[-self.momentum_window:]
        cum = 1.0
        for r in window:
            cum *= 1.0 + r
        momentum = cum - 1.0
        vol_daily = statistics.pstdev(rets[-63:]) if len(rets) >= 63 else statistics.pstdev(rets)
        vol_ann = vol_daily * math.sqrt(252)

        # sigmoid-mapped momentum edge, vol-discounted
        edge = 2.5 * momentum / max(vol_ann, 0.05)
        prob_up = 1.0 / (1.0 + math.exp(-edge))
        prob_up = min(0.85, max(0.15, prob_up))
        expected = momentum * (21 / self.momentum_window) * 0.5
        conf = min(0.9, 0.4 + 0.5 * abs(edge) / (1.0 + abs(edge)))

        f = Forecast(
            symbol=symbol, horizon_days=self.horizon_days,
            prob_up=prob_up, expected_edge=expected, confidence=conf,
            rationale=(
                f"{self.momentum_window}d momentum {momentum:+.1%} at "
                f"{vol_ann:.0%} annualized vol; sigmoid-mapped edge"
            ),
            basis={
                "momentum": momentum, "vol_annualized": vol_ann,
                "edge_z": edge,
            },
            issued_on=snapshot.as_of, agent=self.name,
        )
        return self.pre_register(f)


class BullAgent(Agent):
    """Growth/trend thesis builder. Optimistic prior, must still quantify."""

    def __init__(self, horizon_days: int = 21) -> None:
        super().__init__("bull", horizon_days)

    def forecast(self, snapshot: MarketSnapshot, symbol: str) -> Forecast:
        px = snapshot.closes(symbol)
        if len(px) < 30:
            return _abstain(self.name, snapshot, symbol,
                            self.horizon_days, "insufficient data")
        rets = snapshot.returns(symbol, 252)
        mom_63 = (px[-1] / px[-63]) - 1.0 if len(px) >= 63 else (px[-1] / px[0]) - 1.0
        above_ma50 = px[-1] > (sum(px[-50:]) / min(50, len(px)))
        drawdown_from_high = 1.0 - px[-1] / max(px[-252:])
        # Macro knowledge: the yield curve prices the cycle. A steep curve
        # (slope > 1.5pp) supports risk-taking; inversion drags on every
        # growth thesis.
        slope = (snapshot.macro.get("UST10Y", 0.0) - snapshot.macro.get("UST2Y", 0.0)
                 if "UST10Y" in snapshot.macro and "UST2Y" in snapshot.macro else None)
        curve_adj = 0.0
        if slope is not None:
            if slope < 0:
                curve_adj = -0.08
            elif slope > 1.5:
                curve_adj = +0.06
        prob_up = 0.55 + 0.15 * (mom_63 > 0) + 0.10 * above_ma50 \
            - 0.10 * (drawdown_from_high > 0.20) + curve_adj
        prob_up = min(0.85, max(0.30, prob_up))
        f = Forecast(
            symbol=symbol, horizon_days=self.horizon_days,
            prob_up=prob_up,
            expected_edge=0.04 * (mom_63 > 0) + 0.02 * above_ma50,
            confidence=0.6,
            rationale=(
                f"trend intact: 63d {mom_63:+.1%}, "
                f"{'above' if above_ma50 else 'below'} MA50, "
                f"drawdown {drawdown_from_high:.0%}"
            ),
            basis={"mom_63": mom_63, "above_ma50": float(above_ma50),
                   "drawdown": drawdown_from_high,
                   **({"curve_slope": round(slope, 3)} if slope is not None else {})},
            issued_on=snapshot.as_of, agent=self.name,
        )
        return self.pre_register(f)


class BearAgent(Agent):
    """The falsifier. Its job is to KILL theses, not to balance debate.

    Scores downside risk from vol regime, drawdown depth, and crash
    clustering. A high bear probability does not flip the decision — it
    raises the evidence bar for the thesis to survive the gate.
    """

    def __init__(self, horizon_days: int = 21) -> None:
        super().__init__("bear", horizon_days)

    def forecast(self, snapshot: MarketSnapshot, symbol: str) -> Forecast:
        rets = snapshot.returns(symbol, 252)
        px = snapshot.closes(symbol)
        if len(rets) < 60:
            return _abstain(self.name, snapshot, symbol,
                            self.horizon_days, "insufficient data")
        vol_ann = statistics.pstdev(rets[-63:]) * math.sqrt(252)
        dd = 1.0 - px[-1] / max(px[-252:])
        crash_freq = sum(1 for r in rets[-63:] if r < -0.03) / min(63, len(rets))
        # Macro knowledge: VIX is forward-looking implied vol — the bear
        # reads fear the tape hasn't realized yet.
        vix = snapshot.macro.get("VIX")
        vix_term = min(0.15, max(0.0, (vix - 14.0) / 26.0)) * 0.15 if vix else 0.0
        # Calm regimes sit well below the falsification bar (~0.35);
        # stressed regimes (vol >= 50%, deep drawdown, crash clusters,
        # VIX spikes) breach it. The gradient, not a constant, does the work.
        prob_down = 0.22 + 0.30 * min(1.0, vol_ann / 0.60) \
            + 0.12 * min(1.0, dd / 0.25) + 0.11 * min(1.0, crash_freq / 0.10) \
            + vix_term
        prob_down = min(0.90, prob_down)
        f = Forecast(
            symbol=symbol, horizon_days=self.horizon_days,
            prob_up=1.0 - prob_down,
            expected_edge=-0.5 * prob_down * vol_ann,
            confidence=0.55,
            rationale=(
                f"falsification pressure: vol {vol_ann:.0%}, dd {dd:.0%}, "
                f"crash days {crash_freq:.0%} → P(down) {prob_down:.0%}"
            ),
            basis={"vol_annualized": vol_ann, "drawdown": dd,
                   "crash_frequency": crash_freq, "prob_down": prob_down,
                   **({"vix": vix} if vix else {})},
            issued_on=snapshot.as_of, agent=self.name,
        )
        return self.pre_register(f)


class JudgeAgent(Agent):
    """Aggregates committee forecasts with trust-weighted mega-context fusion.

    The judge sees the *complete* picture — every member's full forecast,
    the macro state, the volatility regime, conviction across the whole
    book, and any recurring-play recall — via CommitteeContext. Context
    adjustments are bounded (<= MAX_CONTEXT_SHIFT total) and every applied
    adjustment is reported back in `basis` for the ledger, so fusion stays
    auditable.
    """

    def __init__(self, horizon_days: int = 21, bear_penalty: float = 0.12) -> None:
        super().__init__("judge", horizon_days)
        self.bear_penalty = bear_penalty

    def forecast(
        self,
        snapshot: MarketSnapshot,
        symbol: str,
        member_forecasts: Optional[list[Forecast]] = None,
        trust: Optional[dict[str, float]] = None,
        context: Optional[CommitteeContext] = None,
    ) -> Forecast:
        members = member_forecasts or []
        weights = trust or {}
        num = 0.0
        den = 0.0
        for f in members:
            w = weights.get(f.agent or "", 1.0)
            w *= (0.25 + f.confidence)
            num += w * f.prob_up
            den += w
        p = num / den if den > 0 else 0.5
        bear = next((f for f in members if f.agent == "bear"), None)
        if bear and bear.prob_up < 0.45:
            # strong falsification pressure: shrink toward agnosticism
            p = p * (1.0 - self.bear_penalty) + 0.5 * self.bear_penalty

        # ---- mega-context adjustments (bounded, logged) ----------------
        applied: dict[str, float] = {}
        if context is not None:
            budget = MAX_CONTEXT_SHIFT

            def apply(key: str, delta: float) -> None:
                nonlocal p, budget
                if abs(delta) < 1e-9 or budget <= 0:
                    return
                step = max(-budget, min(budget, delta))
                p += step
                budget -= abs(step)
                applied[key] = round(step, 4)

            # 1) macro regime: implied fear (VIX) vs. the judge's net view
            vix = context.vix
            if vix is not None:
                if vix >= 30.0:
                    apply("vix_fear", -0.05)
                elif vix <= 14.0:
                    apply("vix_calm", +0.02)
            # 2) macro cycle: curve inversion drags on every long thesis
            slope = context.curve_slope
            if slope is not None and slope < 0:
                apply("curve_inverted", -0.04)
            # 3) cross-symbol conviction: book-wide agreement sharpens edges
            if len(context.cross_symbol) >= 2:
                others = [v for s, v in context.cross_symbol.items() if s != symbol]
                if others and abs(p - 0.5) > 0.03:
                    avg_others = sum(others) / len(others)
                    if (avg_others - 0.5) * (p - 0.5) > 0:
                        apply("cross_symbol_agreement", (avg_others - p) * 0.5)

        p = min(0.9, max(0.1, p))
        return Forecast(
            symbol=symbol, horizon_days=self.horizon_days,
            prob_up=p,
            expected_edge=(p - 0.5) * 0.10,
            confidence=min(0.87, 0.3 + 0.5 * abs(p - 0.5) * 2),
            # deterministic rationale: same inputs -> same bytes (stable
            # content hashes in the ledger across reruns)
            rationale=f"trust-weighted fusion: p={p:.3f} from {len(members)} members",
            basis={"members": len(members), **applied},
            issued_on=snapshot.as_of, agent=self.name,
        )


@dataclass
class CommitteeDecision:
    """One decision day's full output, ready for sizing and the governor."""
    fused: dict[str, Forecast]                  # symbol -> committee call
    verdicts: dict[str, ThesisVerdict]          # symbol -> gate verdict
    members: dict[str, list[Forecast]]          # symbol -> member forecasts
    trust_weights: dict[str, float]
    skill_fires: list[dict] = field(default_factory=list)


class Committee:
    """Single owner of the decision cycle (members, gate, judge, skills).

    The engine hands it a snapshot and the current trust weights; it hands
    back a complete `CommitteeDecision` and writes every artifact — member
    forecasts, gate verdicts, fused calls, skill fires — to the ledger.
    """

    def __init__(
        self,
        ledger: DecisionLedger,
        horizon_days: int = 21,
        skill_book: Optional[RegimeSkillBook] = None,
        decision_bar: float = 0.56,
        bear_penalty: float = 0.12,
    ) -> None:
        self.ledger = ledger
        self.quant = QuantAgent(horizon_days=horizon_days)
        self.bull = BullAgent(horizon_days=horizon_days)
        self.bear = BearAgent(horizon_days=horizon_days)
        self.judge = JudgeAgent(horizon_days=horizon_days, bear_penalty=bear_penalty)
        self.gate = FalsificationGate()
        self.skills = skill_book or RegimeSkillBook(decision_bar=decision_bar)

    # ------------------------------------------------------------------
    def convene(
        self,
        snapshot: MarketSnapshot,
        symbols: list[str],
        trust_weights: dict[str, float],
        use_context: bool = True,
        use_skills: bool = True,
    ) -> CommitteeDecision:
        """Run the full governance cycle for one decision day."""
        # recurring-play distillation: rebuild regime skills from every
        # resolution known as of today (walk-forward by construction)
        self.skills.distill(self.ledger)

        member_fs: list[Forecast] = []
        verdicts: dict[str, ThesisVerdict] = {}
        for s in symbols:
            members = [self.quant.forecast(snapshot, s),
                       self.bull.forecast(snapshot, s),
                       self.bear.forecast(snapshot, s)]
            member_fs += members
            for f in members:
                self.ledger.append("forecast", snapshot.as_of, {
                    "agent": f.agent, "symbol": s,
                    "prob_up": round(f.prob_up, 4),
                    "expected_edge": round(f.expected_edge, 4),
                    "confidence": round(f.confidence, 3),
                    "rationale": f.rationale,
                })
            verdict = self.gate.judge(
                thesis=f"long {s} over {self.judge.horizon_days}d",
                symbol=s, bear=members[2], quant=members[0], snapshot=snapshot,
            )
            verdicts[s] = verdict
            self.ledger.append("thesis", snapshot.as_of, {
                "symbol": s, "survived": verdict.survived,
                "reasons": verdict.reasons,
            })

        # pass 1: trust-weighted fusion establishes the cross-symbol picture
        base: dict[str, Forecast] = {}
        for s in symbols:
            base[s] = self.judge.forecast(
                snapshot, s, self._members_for(member_fs, s), trust_weights)

        # pass 2: mega-context fusion — the judge sees everything at once
        fused: dict[str, Forecast] = {}
        skill_fires: list[dict] = []
        for s in symbols:
            members = self._members_for(member_fs, s)
            ctx = CommitteeContext(
                as_of=snapshot.as_of, symbol=s, macro=dict(snapshot.macro),
                members=members, trust_weights=trust_weights,
                cross_symbol={k: v.prob_up for k, v in base.items()},
            )
            j = self.judge.forecast(snapshot, s, members, trust_weights,
                                    context=ctx) if use_context else base[s]
            # recurring-play recall: nudge confidence where history says
            # this shape of call wins (shrunk; audited to the ledger)
            if use_skills:
                rec = self.skills.recall(snapshot, s, base[s].prob_up)
                if rec and rec["suggested_shift"] > 0:
                    shifted = min(0.90, j.prob_up + rec["suggested_shift"])
                    j = Forecast(
                        symbol=j.symbol, horizon_days=j.horizon_days,
                        prob_up=shifted, expected_edge=(shifted - 0.5) * 0.10,
                        confidence=j.confidence,
                        rationale=j.rationale + " + regime skill",
                        basis=j.basis, issued_on=j.issued_on, agent=j.agent,
                    )
                    fire = {"symbol": s, **rec, "prob_after": round(shifted, 4)}
                    skill_fires.append(fire)
                    self.ledger.append("skill", snapshot.as_of, fire)
            fused[s] = j
            self.ledger.append("committee", snapshot.as_of, {
                "symbol": s, "prob_up": round(j.prob_up, 4),
                "trust_weights": {k: round(v, 3) for k, v in trust_weights.items()},
                "context": j.basis,
            })
        return CommitteeDecision(
            fused=fused, verdicts=verdicts,
            members={s: self._members_for(member_fs, s) for s in symbols},
            trust_weights=trust_weights, skill_fires=skill_fires,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _members_for(member_fs: list[Forecast], symbol: str) -> list[Forecast]:
        return [f for f in member_fs if f.symbol == symbol]
