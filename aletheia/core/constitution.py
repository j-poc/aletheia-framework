"""The constitution: hard risk law that no agent can override.

Unlike prompt-based risk instructions, these constraints are enforced in
code on the *order pipeline* — a confident agent cannot argue its way past
them. Any attempted breach produces a veto with an explicit reason that is
written to the decision ledger.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Constitution:
    """Immutable risk parameters. Frozen at construction."""
    max_single_position: float = 0.20   # max weight per symbol
    max_leverage: float = 1.50          # gross exposure cap
    max_drawdown: float = 0.15          # circuit breaker: stop new risk
    cooldown_days: int = 5              # trading pause after breach
    daily_var_limit: float = 0.020      # one-day 95% VaR cap on the book
    kelly_fraction: float = 0.50        # fractional Kelly multiplier
    require_falsification: bool = True  # thesis gate must pass before entry

    def __post_init__(self) -> None:
        if not 0.0 < self.max_single_position <= 1.0:
            raise ValueError("max_single_position must be in (0, 1]")
        if self.max_leverage < 1.0:
            raise ValueError("max_leverage must be >= 1.0")
        if not 0.0 < self.max_drawdown < 1.0:
            raise ValueError("max_drawdown must be in (0, 1)")
        if not 0.0 < self.kelly_fraction <= 1.0:
            raise ValueError("kelly_fraction must be in (0, 1]")
        if self.daily_var_limit <= 0.0:
            raise ValueError("daily_var_limit must be positive")


@dataclass
class Veto:
    reason: str
    clause: str


@dataclass
class RiskState:
    """Mutable governor state carried across rebalances."""
    in_cooldown: bool = False
    cooldown_remaining: int = 0
    peak_equity: float = 0.0
    last_equity: float = 0.0
    vetoes_issued: int = 0

    def advance_day(self) -> None:
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            self.in_cooldown = self.cooldown_remaining > 0

@dataclass
class RiskCheckResult:
    approved: bool
    adjusted_orders: dict[str, float]
    vetoes: list[Veto] = field(default_factory=list)


class RiskGovernor:
    """Applies the constitution to a proposed target portfolio."""

    def __init__(self, constitution: Constitution) -> None:
        self.c = constitution
        self.state = RiskState()

    @property
    def drawdown_budget_scale(self) -> float:
        """Art. VII: exposure scale from the remaining drawdown allowance.

        As drawdown approaches the constitutional limit, new exposure is
        scaled toward a small probationary floor; at the limit only the
        hard breaker (Art. IV/V) governs. This keeps cumulative loss from
        the all-time high honest — no silent re-baselining.
        """
        dd = self.drawdown
        if dd <= 0 or self.c.max_drawdown <= 0:
            return 1.0
        frac = dd / self.c.max_drawdown
        scale = 1.0 - frac
        return max(0.10, min(1.0, scale))

    def update_equity(self, equity: float) -> None:
        """Track peak equity. First call establishes the baseline (dd = 0)."""
        self.state.last_equity = equity
        if self.state.peak_equity <= 0:
            self.state.peak_equity = equity
        else:
            self.state.peak_equity = max(self.state.peak_equity, equity)

    def enforce_daily(self, equity: float) -> tuple[bool, Optional[Veto]]:
        """Daily circuit-breaker check between committee meetings.

        Trips once on crossing the drawdown limit (Art. IV), flattens the
        book and starts a cooldown; Art. V keeps the book flat until the
        cooldown expires. Never re-trips while already cooling down.
        """
        self.state.last_equity = equity
        if self.state.peak_equity <= 0:
            self.state.peak_equity = equity
        else:
            self.state.peak_equity = max(self.state.peak_equity, equity)
        dd = 1.0 - equity / self.state.peak_equity if self.state.peak_equity > 0 else 0.0
        if dd >= self.c.max_drawdown and not self.state.in_cooldown:
            self.state.in_cooldown = True
            self.state.cooldown_remaining = self.c.cooldown_days
            self.state.vetoes_issued += 1
            return True, Veto(
                clause="IV",
                reason=f"drawdown {dd:.1%} >= limit {self.c.max_drawdown:.1%}; "
                       f"flattening book, {self.c.cooldown_days}d cooldown",
            )
        return False, None

    @property
    def drawdown(self) -> float:
        if self.state.peak_equity <= 0 or self.state.last_equity <= 0:
            return 0.0
        return 1.0 - (self.state.last_equity / self.state.peak_equity)

    def check(
        self,
        target: dict[str, float],
        current: dict[str, float],
        equity: float,
        vol_by_symbol: dict[str, float],
        thesis_gate: Optional[dict[str, bool]] = None,
    ) -> RiskCheckResult:
        """Validate/repair a proposed allocation against the constitution.

        target/current are dicts of symbol -> signed weight (cash implicit).
        vol_by_symbol: symbol -> annualized vol (decimal). Returns approved
        (possibly adjusted) allocation plus vetoes for every clause hit.
        """
        vetoes: list[Veto] = []
        adjusted: dict[str, float] = {}

        # Art. IV — drawdown circuit breaker (vs. peak equity).
        # Fires once on crossing; Art. V governs while cooldown is active.
        dd = (1.0 - equity / self.state.peak_equity) \
            if self.state.peak_equity > 0 else 0.0
        if dd >= self.c.max_drawdown and not self.state.in_cooldown:
            vetoes.append(Veto(
                clause="IV",
                reason=f"drawdown {dd:.1%} >= limit {self.c.max_drawdown:.1%}; "
                       f"de-risking and entering {self.c.cooldown_days}d cooldown",
            ))
            adjusted = {s: 0.0 for s in set(target) | set(current)}
            self.state.in_cooldown = True
            self.state.cooldown_remaining = self.c.cooldown_days
            self.state.vetoes_issued += 1
            return RiskCheckResult(False, adjusted, vetoes)

        # Art. V — cooldown forbids new risk; existing book may be held.
        if self.state.in_cooldown:
            if any(abs(w) > 1e-9 and abs(current.get(s, 0.0)) < 1e-9
                   for s, w in target.items()):
                vetoes.append(Veto(
                    clause="V",
                    reason=f"cooldown active ({self.state.cooldown_remaining}d left); "
                           "no new positions may be opened",
                ))
            # keep only existing, capped positions during cooldown
            for s, w in current.items():
                adjusted[s] = max(min(w, self.c.max_single_position),
                                  -self.c.max_single_position)
            self.state.vetoes_issued += len(vetoes)
            return RiskCheckResult(not vetoes, adjusted, vetoes)

        working = dict(target)

        # Art. VII — drawdown budget: scale exposure with remaining allowance.
        # Silent while dd < 3% (normal equity wiggle); vetoed and scaled
        # once the remaining allowance drops below 80%.
        budget = self.drawdown_budget_scale
        if budget <= 0.80:
            vetoes.append(Veto(
                clause="VII",
                reason=f"drawdown budget {budget:.0%} of normal exposure "
                       f"(dd {self.drawdown:.1%} of {self.c.max_drawdown:.1%} limit)",
            ))
            working = {s: w * budget for s, w in working.items()}
        elif budget < 0.999:
            working = {s: w * budget for s, w in working.items()}

        # Art. III — falsification gate.
        if self.c.require_falsification and thesis_gate:
            for s, passed in thesis_gate.items():
                if not passed and abs(working.get(s, 0.0)) > 1e-9:
                    vetoes.append(Veto(
                        clause="III",
                        reason=f"{s}: thesis failed adversarial gate; entry blocked",
                    ))
                    working[s] = 0.0

        # Art. I — position caps.
        for s in list(working):
            cap = self.c.max_single_position
            if abs(working[s]) > cap + 1e-12:
                vetoes.append(Veto(
                    clause="I",
                    reason=f"{s}: |weight| {abs(working[s]):.1%} > cap {cap:.0%}; clipped",
                ))
                working[s] = math.copysign(cap, working[s])

        # Art. II — gross leverage cap (proportional scale-down).
        gross = sum(abs(w) for w in working.values())
        if gross > self.c.max_leverage + 1e-12:
            vetoes.append(Veto(
                clause="II",
                reason=f"gross exposure {gross:.2f} > {self.c.max_leverage:.2f}; "
                       "scaled down proportionally",
            ))
            scale = self.c.max_leverage / gross
            working = {s: w * scale for s, w in working.items()}

        # Art. VI — one-day 95% VaR cap: VaR_i = |w_i| * 1.65 * sigma_daily,
        # with sigma_daily = sigma_annual / sqrt(252).
        var_est = sum(
            abs(w) * 1.65 * (vol_by_symbol.get(s, 0.30) / math.sqrt(252.0))
            for s, w in working.items()
        )
        if var_est > self.c.daily_var_limit + 1e-12:
            vetoes.append(Veto(
                clause="VI",
                reason=f"book VaR {var_est:.2%} > {self.c.daily_var_limit:.2%}; "
                       "scaled to comply",
            ))
            scale = self.c.daily_var_limit / var_est
            working = {s: w * scale for s, w in working.items()}

        self.state.vetoes_issued += len(vetoes)
        return RiskCheckResult(True, working, vetoes)
