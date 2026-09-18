"""Walk-forward decision engine with daily constitutional enforcement.

On each DECISION day (every `rebalance_every` sessions) the Committee
convenes (its own module); the engine handles everything downstream of a
decision: sizing, the RiskGovernor's constitutional check, order/cost
simulation, daily marking, and forecast grading.

Timeline of one run:

1. point-in-time snapshot (no look-ahead)
2. Committee.convene(): forecasts → falsification gate → judge fusion
   → skill recall; every artifact written to the ledger
3. sizing proposal: edge-gated, vol-targeted, Kelly-capped
4. the RiskGovernor applies the constitution; every veto is logged
5. forecasts, vetoes and orders all hit the hash-chained ledger
6. H days later every forecast is resolved and trust weights update

On EVERY day — decision or not — the engine marks the book to market and
the governor re-checks the drawdown circuit breaker. Risk law is enforced
daily, not just when the committee happens to meet.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Optional

from aletheia.agents.committee import Committee
from aletheia.agents.skills import regime_of
from aletheia.calibration.ledger import DecisionLedger
from aletheia.calibration.trust import TrustModel
from aletheia.core.constitution import Constitution, RiskGovernor
from aletheia.core.types import Forecast, MarketSnapshot, ResolutionRecord
from aletheia.data.providers import DataProvider


@dataclass
class EngineConfig:
    """All engine knobs, including the ablation toggles, in one place."""
    initial_capital: float = 1_000_000.0
    rebalance_every: int = 5
    horizon_days: int = 21
    cost_bps: float = 5.0
    min_edge: float = 0.005
    threshold_prob_up: float = 0.56
    # governance levers (ablation toggles)
    trust_enabled: bool = True
    skills_enabled: bool = True
    macro_enabled: bool = True    # agents read VIX / yield curve
    context_enabled: bool = True  # judge fuses with full CommitteeContext


class DecisionEngine:
    """The full calibration-governed committee loop."""

    def __init__(
        self,
        provider: DataProvider,
        symbols: list[str],
        constitution: Optional[Constitution] = None,
        config: Optional[EngineConfig] = None,
        ledger: Optional[DecisionLedger] = None,
    ) -> None:
        self.provider = provider
        self.symbols = symbols
        self.constitution = constitution or Constitution()
        self.cfg = config or EngineConfig()
        self.ledger = ledger or DecisionLedger()
        self.governor = RiskGovernor(self.constitution)
        self.committee = Committee(
            ledger=self.ledger, horizon_days=self.cfg.horizon_days,
            decision_bar=self.cfg.threshold_prob_up,
        )
        self.trust = TrustModel(names=["quant", "bull", "bear", "judge"])
        self.equity = self.cfg.initial_capital
        self.equity_curve: list[tuple[date, float]] = []
        self.positions: dict[str, float] = {}
        self.entry_px: dict[str, float] = {}
        self.pending: list[tuple[Forecast, date]] = []
        self.resolved_log: list[Forecast] = []
        self.n_decision_days = 0

    # ------------------------------------------------------------------
    def _snapshot(self, as_of: date, lookback: int = 260) -> MarketSnapshot:
        snap = self.provider.get_snapshot(self.symbols, as_of, lookback=lookback)
        if not self.cfg.macro_enabled:
            snap.macro = {}  # ablation: committee trades without macro knowledge
        return snap

    def _resolve_matured(self, as_of: date, snapshot: MarketSnapshot) -> None:
        """Grade forecasts that reached their horizon; update trust.

        Grading is NET of round-trip trading cost: the outcome is True only
        if the move exceeded the cost of acting on the call. An agent earns
        credit for edge that was actually tradable, not for epsilon drift.
        """
        still: list[tuple[Forecast, date]] = []
        h = self.cfg.horizon_days
        rt_cost = 2.0 * self.cfg.cost_bps / 10_000
        for f, resolve_on in self.pending:
            if as_of >= resolve_on:
                px = snapshot.closes(f.symbol)
                if len(px) >= h + 1:
                    gross_move = px[-1] / px[-1 - h] - 1.0
                    outcome = gross_move > rt_cost
                    resolved = f.with_resolution(as_of, outcome)
                    self.resolved_log.append(resolved)
                    if f.agent and f.confidence > 0 and self.cfg.trust_enabled:
                        self.trust.record_forecast(f.agent, f.prob_up, outcome)
                    self.ledger.append("resolution", as_of, ResolutionRecord(
                        symbol=f.symbol, agent=f.agent or "unclassified",
                        prob_up=f.prob_up, outcome=outcome,
                        confidence=f.confidence,
                        regime=regime_of(snapshot, f.symbol),
                    ).to_payload())
                else:
                    # keep trying: a short provider history must not turn
                    # into a silent never-resolve (forecast stays pending)
                    still.append((f, resolve_on))
            else:
                still.append((f, resolve_on))
        self.pending = still

    def _sizing(self, f: Forecast, vol_by_symbol: dict[str, float]) -> float:
        """Committee sizing: edge-gated, vol-targeted, Kelly-capped."""
        if f.prob_up < self.cfg.threshold_prob_up or f.expected_edge < self.cfg.min_edge:
            return 0.0
        vol = vol_by_symbol.get(f.symbol, 0.25)
        w_vol = 0.15 / max(vol, 0.05)
        w_kelly = self.constitution.kelly_fraction * (2.0 * f.prob_up - 1.0)
        w = min(w_vol, w_kelly)
        return round(min(max(w, 0.0), 0.35), 4)

    def _vol_by_symbol(self, snapshot: MarketSnapshot) -> dict[str, float]:
        out = {}
        for s in self.symbols:
            rets = snapshot.returns(s, 63)
            out[s] = statistics.pstdev(rets) * math.sqrt(252) if len(rets) >= 20 else 0.30
        return out

    def _decision_cycle(self, as_of: date, snap: MarketSnapshot, i: int,
                        cal_dates: list[date]) -> None:
        """One committee meeting plus its execution consequences."""
        self.n_decision_days += 1
        self._resolve_matured(as_of, snap)

        decision = self.committee.convene(
            snap, self.symbols, self.trust.weights(),
            use_context=self.cfg.context_enabled,
            use_skills=self.cfg.skills_enabled,
        )

        vols = self._vol_by_symbol(snap)
        proposal = {s: w for s in self.symbols
                    if (w := self._sizing(decision.fused[s], vols)) > 0}
        gate_map = {s: v.survived for s, v in decision.verdicts.items()}
        result = self.governor.check(proposal, self.positions, self.equity, vols, gate_map)
        for v in result.vetoes:
            self.ledger.append("veto", as_of, {"clause": v.clause, "reason": v.reason})

        weights_prev = self.positions
        turnover = sum(
            abs(result.adjusted_orders.get(s, 0.0) - weights_prev.get(s, 0.0))
            for s in set(result.adjusted_orders) | set(weights_prev)
        )
        cost = turnover * self.cfg.cost_bps / 10_000
        self.equity *= (1.0 - cost)
        self.positions = result.adjusted_orders
        self.entry_px = {s: snap.closes(s)[-1]
                         for s in self.positions if snap.closes(s)}

        if self.positions:
            self.ledger.append("order", as_of, {
                "weights": {s: round(w, 4) for s, w in self.positions.items()},
                "equity": round(self.equity, 2),
                "turnover": round(turnover, 4),
            })

        # member forecasts + the fused call all get graded
        resolve_on = cal_dates[min(i + self.cfg.horizon_days, len(cal_dates) - 1)]
        for s in self.symbols:
            for f in decision.members[s] + [decision.fused[s]]:
                self.pending.append((f, resolve_on))

    # ------------------------------------------------------------------
    def run(self, start: date, end: date) -> dict:
        """Walk forward daily; decide every `rebalance_every` sessions."""
        self.ledger.append("session", start, {
            "symbols": self.symbols,
            "constitution": {
                "max_single_position": self.constitution.max_single_position,
                "max_leverage": self.constitution.max_leverage,
                "max_drawdown": self.constitution.max_drawdown,
                "daily_var_limit": self.constitution.daily_var_limit,
                "kelly_fraction": self.constitution.kelly_fraction,
            },
            "initial_capital": self.cfg.initial_capital,
        })

        full = self.provider.get_snapshot(self.symbols, end, lookback=100_000)
        bars = full.bars.get(self.symbols[0], [])
        cal_dates = [b.date for b in bars if start <= b.date <= end]
        if len(cal_dates) < 60:
            raise RuntimeError("not enough trading days in range")

        warmup = 60
        for i in range(warmup, len(cal_dates)):
            as_of = cal_dates[i]
            snap = self._snapshot(as_of)

            # 0) risk clock: cooldown countdown runs daily
            self.governor.state.advance_day()

            # 1) committee cycle on decision days
            is_decision = ((i - warmup) % self.cfg.rebalance_every) == 0
            if is_decision:
                self._decision_cycle(as_of, snap, i, cal_dates)

            # 2) mark book to market (daily, one day of pnl per mark)
            pnl = 0.0
            for s, w in self.positions.items():
                px = snap.closes(s)
                if s in self.entry_px and px and self.entry_px[s] > 0:
                    pnl += w * (px[-1] / self.entry_px[s] - 1.0)
            self.equity *= (1.0 + pnl)
            self.entry_px = {s: snap.closes(s)[-1]
                             for s in self.positions if snap.closes(s)}
            self.equity_curve.append((as_of, self.equity))
            self.governor.update_equity(self.equity)

            # 3) daily constitutional enforcement (Art. IV)
            tripped, veto = self.governor.enforce_daily(self.equity)
            if tripped:
                self.ledger.append("veto", as_of, {
                    "clause": veto.clause, "reason": veto.reason, "daily": True,
                })
                self.positions = {}
                self.entry_px = {}

        self.ledger.append("session_end", end, {
            "final_equity": round(self.equity, 2),
            "total_vetoes": self.governor.state.vetoes_issued,
            "decision_days": self.n_decision_days,
        })
        return self.report()

    # ------------------------------------------------------------------
    def report(self) -> dict:
        curve = self.equity_curve
        rets = [curve[i][1] / curve[i - 1][1] - 1.0 for i in range(1, len(curve))]
        ann = math.sqrt(252)
        mean_d = statistics.mean(rets) if rets else 0.0
        sd_d = statistics.pstdev(rets) if len(rets) > 1 else 1e-9
        sharpe = (mean_d / sd_d) * ann if sd_d > 0 else 0.0
        peak = curve[0][1] if curve else 1.0
        max_dd = 0.0
        for _, v in curve:
            peak = max(peak, v)
            if peak > 0:
                max_dd = max(max_dd, 1.0 - v / peak)
        total = curve[-1][1] / curve[0][1] - 1.0 if curve else 0.0
        briers = [f.brier for f in self.resolved_log if f.brier is not None]
        absten = sum(1 for f in self.resolved_log if f.confidence <= 0)
        graded = [f for f in self.resolved_log if f.confidence > 0]
        hit_rate = (sum(1 for f in graded if (f.outcome and f.prob_up > 0.5)
                        or (not f.outcome and f.prob_up < 0.5)) / len(graded)) if graded else None
        return {
            "total_return": round(total, 4),
            "sharpe": round(sharpe, 2),
            "max_drawdown": round(max_dd, 4),
            "final_equity": round(self.equity, 2),
            "n_days": len(curve),
            "n_decisions": self.n_decision_days,
            "n_vetoes": self.governor.state.vetoes_issued,
            "ledger_len": len(self.ledger.entries),
            "ledger_valid": self.ledger.verify()[0],
            "trust_weights": {k: round(v, 3) for k, v in self.trust.weights().items()},
            "calibration": {
                a: {"n": r.n,
                    "brier": round(r.mean_brier, 4) if r.n else None,
                    "ece": round(r.ece(), 4) if r.n else None}
                for a, r in self.trust.records.items()
            },
            "mean_brier_all": round(statistics.mean(briers), 4) if briers else None,
            "graded_forecasts": len(graded),
            "abstentions": absten,
            "directional_hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
        }


def run_ablation(provider, symbols, start, end, disable):
    """Run the engine with one governance mechanism disabled.

    disable: subset of {"falsification", "trust", "constitution", "skills",
    "macro", "context"}.
    """
    from aletheia.core.constitution import Constitution
    const = Constitution()
    if "constitution" in disable:
        const = Constitution(
            max_single_position=1.0, max_leverage=10.0, max_drawdown=0.95,
            daily_var_limit=10.0, kelly_fraction=1.0, require_falsification=False,
        )
    elif "falsification" in disable:
        const = Constitution(require_falsification=False)
    cfg = EngineConfig(
        trust_enabled="trust" not in disable,
        skills_enabled="skills" not in disable,
        macro_enabled="macro" not in disable,
        context_enabled="context" not in disable,
    )
    eng = DecisionEngine(provider, symbols, constitution=const, config=cfg)
    if "trust" in disable:
        eng.committee.judge.bear_penalty = 0.0
    return eng.run(start, end)
