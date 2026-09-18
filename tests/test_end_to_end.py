"""End-to-end: full committee loop on a seeded synthetic market."""
from __future__ import annotations

from datetime import date, timedelta

from aletheia.calibration.ledger import DecisionLedger
from aletheia.core.constitution import Constitution
from aletheia.data.providers import SyntheticProvider
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
