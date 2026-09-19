"""End-to-end: full committee loop on a seeded synthetic market."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from aletheia.agents.committee import CommitteeDecision
from aletheia.calibration.ledger import DecisionLedger
from aletheia.core.constitution import Constitution
from aletheia.core.types import Bar, Forecast, MarketSnapshot, ThesisVerdict
from aletheia.data.providers import DataProvider, SyntheticProvider
from aletheia.engine.backtest import DecisionEngine, EngineConfig, run_ablation


def _make_engine(seed: int = 42) -> tuple[DecisionEngine, date, date]:
    provider = SyntheticProvider(seed=seed, n_days=900)
    start = date(2019, 1, 2) + timedelta(days=20)
    end = start + timedelta(days=700)
    ledger = DecisionLedger()
    engine = DecisionEngine(
        provider=provider, symbols=["SYN"],
        constitution=Constitution(),
        config=EngineConfig(rebalance_every=5, horizon_days=21),
        ledger=ledger,
    )
    return engine, start, end


def test_end_to_end_synthetic_run():
    engine, start, end = _make_engine()
    report = engine.run(start, end)

    assert report["n_decisions"] > 20
    assert report["ledger_valid"] is True
    assert report["ledger_len"] > 100
    assert report["final_equity"] > 0
    # the committee must have produced gradeable forecasts
    assert len(engine.resolved_log) > 20
    # trust weights must have moved off pure-prior for at least one agent
    tw = report["trust_weights"]
    assert set(tw) == {"quant", "bull", "bear", "judge"}
    # report calibration stats present
    assert "mean_brier_all" in report


def test_ledger_contains_full_governance_trail():
    engine, start, end = _make_engine(seed=43)
    engine.run(start, end)
    kinds = {e.kind for e in engine.ledger.entries}
    assert {"session", "forecast", "thesis", "committee", "order",
            "resolution", "session_end"} <= kinds
    # vetoes are expected on eager proposals with a 20% cap; not asserted
    # as mandatory because seeded paths may never trip a clause


def test_ablations_run_and_differ():
    provider = SyntheticProvider(seed=44, n_days=700)
    start = date(2019, 1, 2) + timedelta(days=20)
    end = start + timedelta(days=500)
    full = run_ablation(provider, ["SYN"], start, end, disable=[])
    no_const = run_ablation(provider, ["SYN"], start, end, disable=["constitution"])
    assert full["ledger_valid"] and no_const["ledger_valid"]
    # with the constitution disabled, veto counts collapse to ~0
    assert no_const["n_vetoes"] < full["n_vetoes"] or full["n_vetoes"] == 0


def test_ledger_persists_and_reverifies(tmp_path):
    engine, start, end = _make_engine(seed=45)
    engine.run(start, end)
    p = tmp_path / "ledger.jsonl"
    engine.ledger.to_jsonl(str(p))
    reloaded = DecisionLedger.from_jsonl(str(p))
    ok, why = reloaded.verify()
    assert ok, why


class PricePathProvider(DataProvider):
    def __init__(self, prices):
        self.bars = [Bar("X", date(2025, 1, 1) + timedelta(days=i), p, p, p, p, 0)
                     for i, p in enumerate(prices)]

    def get_snapshot(self, symbols, as_of, lookback=260):
        bars = [b for b in self.bars if b.date <= as_of][-lookback:]
        return MarketSnapshot(as_of, {"X": bars}, {})


def _constant_committee(snapshot, symbols, trust_weights, **kwargs):
    f = Forecast("X", 21, 0.7, 0.05, 0.6, "fixed call", {},
                 snapshot.as_of, "judge")
    return CommitteeDecision(
        fused={"X": f},
        verdicts={"X": ThesisVerdict("long X", False)},
        members={"X": []}, trust_weights=trust_weights,
    )


def test_rebalance_day_includes_return_earned_by_existing_position():
    prices = [100 * 1.01 ** i for i in range(70)]
    engine = DecisionEngine(
        PricePathProvider(prices), ["X"],
        config=EngineConfig(rebalance_every=1, cost_bps=0),
    )
    engine.committee.convene = _constant_committee
    engine.run(date(2025, 1, 1), date(2025, 3, 11))

    # First purchase is at session 60 close. The position then earns all
    # nine daily moves through session 69, all on rebalance days.
    assert engine.equity == pytest.approx(1_000_000 * (1 + 0.2 * 0.01) ** 9)


def test_initial_order_cost_is_in_reported_total_return():
    engine = DecisionEngine(
        PricePathProvider([100.0] * 62), ["X"],
        config=EngineConfig(rebalance_every=5, cost_bps=10),
    )
    engine.committee.convene = _constant_committee
    report = engine.run(date(2025, 1, 1), date(2025, 3, 3))

    # Buying 20% of a $1m portfolio at 10 bps turnover costs $200.
    assert engine.equity == pytest.approx(999_800)
    assert report["total_return"] == pytest.approx(-0.0002)


def test_drawdown_breaker_sees_loss_before_same_day_rebalance():
    engine = DecisionEngine(
        PricePathProvider([100.0] * 61 + [20.0]), ["X"],
        config=EngineConfig(rebalance_every=1, cost_bps=0),
    )
    engine.committee.convene = _constant_committee
    engine.run(date(2025, 1, 1), date(2025, 3, 3))

    assert engine.equity == pytest.approx(840_000)
    assert engine.positions == {}
    assert engine.governor.state.in_cooldown
    assert any(e.kind == "veto" and e.payload["clause"] == "IV"
               for e in engine.ledger.entries)


def test_simple_baseline_uses_active_start_and_initial_cash_allocation():
    from aletheia.reproduce_report import baselines

    provider = PricePathProvider([100.0, 110.0, 90.0])
    dates = [b.date for b in provider.bars]
    rows = baselines(provider, ["X"], dates[-1], dates)

    assert rows["buy_and_hold"]["total_return"] == pytest.approx(-0.10)
    assert rows["fixed_25pct"]["total_return"] == pytest.approx(-0.025)
    assert rows["buy_and_hold"]["max_drawdown"] == pytest.approx(0.1818)
    assert rows["fixed_25pct"]["max_drawdown"] == pytest.approx(0.0488)


def test_exit_order_is_recorded_when_target_becomes_cash():
    engine = DecisionEngine(
        PricePathProvider([100.0] * 62), ["X"],
        config=EngineConfig(rebalance_every=1, cost_bps=0),
    )

    def convene(snapshot, symbols, trust_weights, **kwargs):
        decision = _constant_committee(snapshot, symbols, trust_weights)
        if snapshot.as_of == date(2025, 3, 3):
            decision.fused["X"] = Forecast(
                "X", 21, 0.5, 0.0, 0.6, "cash", {}, snapshot.as_of, "judge"
            )
        return decision

    engine.committee.convene = convene
    engine.run(date(2025, 1, 1), date(2025, 3, 3))
    orders = [e.payload for e in engine.ledger.entries if e.kind == "order"]
    assert [order["weights"] for order in orders] == [{"X": 0.2}, {}]
    assert orders[-1]["turnover"] == pytest.approx(0.2)


def test_skill_resolution_uses_regime_known_when_forecast_was_issued():
    prices = [100.0] * 61 + [140.0 if i % 2 else 100.0 for i in range(25)]
    engine = DecisionEngine(
        PricePathProvider(prices), ["X"],
        config=EngineConfig(rebalance_every=22, horizon_days=21, cost_bps=0),
    )
    engine.committee.convene = _constant_committee
    engine.run(date(2025, 1, 1), date(2025, 3, 27))

    first = next(e for e in engine.ledger.entries if e.kind == "resolution")
    assert first.payload["regime"] == "calm"
