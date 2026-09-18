"""Tests for constitution enforcement, calibration trust, and the ledger."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from aletheia.calibration.ledger import DecisionLedger
from aletheia.calibration.trust import CalibrationRecord, TrustModel, trust_weight
from aletheia.core.constitution import Constitution, RiskGovernor
from aletheia.core.types import Forecast, MarketSnapshot
from aletheia.agents.gate import FalsificationGate


def _mk_forecast(agent="quant", prob=0.6, conf=0.6, sym="SPX", edge=0.02):
    return Forecast(
        symbol=sym, horizon_days=21, prob_up=prob, expected_edge=edge,
        confidence=conf, rationale="test", basis={"edge_z": 0.5},
        issued_on=date(2025, 1, 1), agent=agent,
    )


# ----------------------------------------------------------------------
# Constitution / RiskGovernor
# ----------------------------------------------------------------------
class TestConstitution:
    def test_rejects_invalid_params(self):
        with pytest.raises(ValueError):
            Constitution(max_single_position=0.0)
        with pytest.raises(ValueError):
            Constitution(max_drawdown=1.5)
        with pytest.raises(ValueError):
            Constitution(kelly_fraction=0.0)

    def test_position_cap_enforced(self):
        gov = RiskGovernor(Constitution())
        res = gov.check({"SPX": 0.45}, {}, 1_000_000, {"SPX": 0.2}, {"SPX": True})
        assert res.adjusted_orders["SPX"] == pytest.approx(0.20)
        assert any(v.clause == "I" for v in res.vetoes)

    def test_leverage_cap_scales_proportionally(self):
        gov = RiskGovernor(Constitution(max_single_position=0.9))
        res = gov.check(
            {"A": 0.8, "B": 0.8}, {}, 1_000_000,
            {"A": 0.1, "B": 0.1}, {"A": True, "B": True},
        )
        gross = sum(abs(w) for w in res.adjusted_orders.values())
        assert gross <= 1.5 + 1e-9
        assert any(v.clause == "II" for v in res.vetoes)

    def test_var_cap_binds(self):
        # raise the position cap so Art. I doesn't clip before Art. VI fires
        gov = RiskGovernor(Constitution(max_single_position=0.9))
        vols = {"A": 0.5}
        res = gov.check({"A": 0.45}, {}, 1_000_000, vols, {"A": True})
        w = res.adjusted_orders["A"]
        var_daily = w * 1.65 * (0.5 / 252 ** 0.5)
        assert var_daily <= 0.020 + 1e-9
        assert any(v.clause == "VI" for v in res.vetoes)

    def test_falsification_gate_blocks_entries(self):
        gov = RiskGovernor(Constitution())
        res = gov.check({"SPX": 0.1}, {}, 1_000_000, {"SPX": 0.2}, {"SPX": False})
        assert res.adjusted_orders["SPX"] == 0.0
        assert any(v.clause == "III" for v in res.vetoes)

    def test_drawdown_circuit_breaker(self):
        gov = RiskGovernor(Constitution(max_drawdown=0.10))
        gov.update_equity(1_000_000)
        gov.update_equity(890_000)  # -11%
        res = gov.check({"SPX": 0.1}, {}, 890_000, {"SPX": 0.2}, {"SPX": True})
        assert not res.approved
        assert all(w == 0.0 for w in res.adjusted_orders.values())
        # cooldown forbids reopening
        gov2_state = gov.state
        assert gov2_state.in_cooldown
        res2 = gov.check({"SPX": 0.1}, {}, 890_000, {"SPX": 0.2}, {"SPX": True})
        assert any(v.clause == "V" for v in res2.vetoes)


# ----------------------------------------------------------------------
# Calibration & trust
# ----------------------------------------------------------------------
class TestCalibration:
    def test_brier_extremes(self):
        from aletheia.calibration.trust import brier_score
        assert brier_score(0.9, True) == pytest.approx(0.01)
        assert brier_score(0.9, False) == pytest.approx(0.81)

    def test_perfect_forecaster_earns_ceiling(self):
        rec = CalibrationRecord(name="x")
        for _ in range(200):
            rec.add(0.9, True)
            rec.add(0.1, False)
        w = trust_weight(rec)
        assert w > 2.5  # approaches ceiling

    def test_worst_forecaster_earns_floor(self):
        rec = CalibrationRecord(name="x")
        for _ in range(200):
            rec.add(0.9, False)
            rec.add(0.1, True)
        w = trust_weight(rec)
        assert w < 0.2  # approaches floor

    def test_small_sample_shrinks_to_prior(self):
        rec = CalibrationRecord(name="x")
        for _ in range(2):
            rec.add(0.9, True)
        w = trust_weight(rec)
        assert 0.9 < w < 1.6  # shrunk toward 1.0

    def test_trust_model_normalizes(self):
        tm = TrustModel(names=["a", "b", "c"])
        for _ in range(100):
            tm.record_forecast("a", 0.9, True)   # excellent
            tm.record_forecast("b", 0.5, True)   # random
            tm.record_forecast("c", 0.9, False)  # awful
        w = tm.weights()
        assert w["a"] == max(w.values())
        assert w["c"] == min(w.values())
        assert sum(tm.normalize(w).values()) == pytest.approx(1.0)

    def test_calibration_curve_ece(self):
        rec = CalibrationRecord(name="x")
        for _ in range(100):
            rec.add(0.8, True)
            rec.add(0.8, False)
        assert rec.ece() > 0.1  # poorly calibrated at 0.8 bucket


# ----------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------
class TestLedger:
    def test_chain_verifies(self):
        led = DecisionLedger()
        led.append("note", date(2025, 1, 1), {"a": 1})
        led.append("note", date(2025, 1, 2), {"a": 2})
        ok, why = led.verify()
        assert ok, why

    def test_tamper_detection(self):
        led = DecisionLedger()
        led.append("note", date(2025, 1, 1), {"a": 1})
        led.append("note", date(2025, 1, 2), {"a": 2})
        led.entries[0].payload["a"] = 999  # rewrite history
        ok, why = led.verify()
        assert not ok
        assert "tampered" in why or "mismatch" in why

    def test_jsonl_roundtrip(self, tmp_path):
        led = DecisionLedger()
        led.append("forecast", date(2025, 1, 1), {"prob": 0.7})
        p = tmp_path / "ledger.jsonl"
        led.to_jsonl(str(p))
        led2 = DecisionLedger.from_jsonl(str(p))
        assert len(led2.entries) == 1
        ok, _ = led2.verify()
        assert ok


# ----------------------------------------------------------------------
# Falsification gate
# ----------------------------------------------------------------------
class TestGate:
    def test_no_falsifier_rejects(self):
        g = FalsificationGate()
        v = g.judge("long X", "X", bear=None, quant=None)
        assert v.falsified

    def test_strong_bear_falsifies(self):
        g = FalsificationGate()
        bear = _mk_forecast(agent="bear", prob=0.30, conf=0.6)
        quant = _mk_forecast(agent="quant", prob=0.70)
        v = g.judge("long X", "X", bear=bear, quant=quant)
        assert v.falsified

    def test_thesis_survives_calm_regime(self):
        g = FalsificationGate()
        bear = _mk_forecast(agent="bear", prob=0.80, conf=0.6)
        quant = _mk_forecast(agent="quant", prob=0.70)
        v = g.judge("long X", "X", bear=bear, quant=quant)
        assert v.survived

    def test_snapshot_requires_bars(self):
        """Snapshot returns helper works on empty bars."""
        snap = MarketSnapshot(as_of=date(2025, 1, 1), bars={}, macro={})
        assert snap.closes("NOPE") == []


class TestJudgeMegaContext:
    """The talk's 'one agent with all the mega context' lesson, bounded."""

    def _members(self):
        return [
            _mk_forecast(agent="quant", prob=0.65, conf=0.7),
            _mk_forecast(agent="bull", prob=0.75, conf=0.6),
            _mk_forecast(agent="bear", prob=0.55, conf=0.6),
        ]

    def test_context_adjustments_are_bounded(self):
        from aletheia.agents.context import CommitteeContext
        from aletheia.agents.committee import JudgeAgent
        snap = MarketSnapshot(as_of=date(2025, 1, 1), bars={},
                              macro={"VIX": 38.0, "UST10Y": 3.0, "UST2Y": 4.0})
        judge = JudgeAgent()
        ctx = CommitteeContext(as_of=snap.as_of, symbol="X", macro=snap.macro,
                               regime="stressed", members=self._members(),
                               trust_weights={}, cross_symbol={"X": 0.65, "Y": 0.70})
        with_ctx = judge.forecast(snap, "X", self._members(), {}, context=ctx)
        without = judge.forecast(snap, "X", self._members(), {})
        # bounded: the judge may never move more than 10pp on context
        assert abs(with_ctx.prob_up - without.prob_up) <= 0.10 + 1e-9
        # and the applied adjustments are transparent
        applied = {k: v for k, v in with_ctx.basis.items() if k != "members"}
        assert applied  # something was applied under VIX 38 + inversion

    def test_no_context_no_adjustments(self):
        from aletheia.agents.committee import JudgeAgent
        snap = MarketSnapshot(as_of=date(2025, 1, 1), bars={},
                              macro={"VIX": 38.0})
        j = JudgeAgent().forecast(snap, "X", self._members(), {})
        assert set(j.basis) == {"members"}

    def test_macro_flows_to_bear(self):
        from aletheia.data.providers import SyntheticProvider
        from aletheia.agents.committee import BearAgent
        snap = SyntheticProvider(seed=1).get_snapshot(["SYN"], date(2020, 1, 1))
        snap.macro["VIX"] = 45.0
        bear_hi = BearAgent().forecast(snap, "SYN")
        snap.macro["VIX"] = 12.0
        bear_lo = BearAgent().forecast(snap, "SYN")
        assert bear_hi.prob_up < bear_lo.prob_up  # fear raises P(down)


# ----------------------------------------------------------------------
# Data-layer fail-fast behavior (production cold-start contract)
# ----------------------------------------------------------------------
class TestFredFailFast:
    def _no_network_provider(self, tmp_path):
        from aletheia.data.providers import FredProvider
        import aletheia.data.providers as prov

        original = prov._http_get
        prov._http_get = lambda url, timeout=20: (_ for _ in ()).throw(
            OSError("network unreachable"))
        return FredProvider(cache_dir=str(tmp_path)), prov, original

    def test_unreachable_network_raises_actionable_error(self, tmp_path):
        """Cold start with no cache and no network: fail fast, loudly."""
        from datetime import date as d
        provider, prov, original = self._no_network_provider(tmp_path)
        try:
            with pytest.raises(RuntimeError, match="cannot load FRED series"):
                provider.get_snapshot(["SPX"], d(2026, 1, 1))
        finally:
            prov._http_get = original

    def test_cached_series_survives_network_outage(self, tmp_path):
        """A populated cache makes the provider fully offline-capable."""
        from datetime import date as d
        from aletheia.data.providers import FredProvider
        import aletheia.data.providers as prov

        original = prov._http_get
        prov._http_get = lambda url, timeout=20: (
            b"observation_date,SP500\n2026-01-02,5000.0\n2026-01-05,5010.0\n")
        try:
            warm = FredProvider(cache_dir=str(tmp_path))
            snap = warm.get_snapshot(["SPX"], d(2026, 2, 1))
            assert snap.closes("SPX")[-1] == 5010.0
        finally:
            prov._http_get = original
        # now the network dies; the cached series must still load
        prov._http_get = lambda url, timeout=20: (_ for _ in ()).throw(
            OSError("network unreachable"))
        try:
            cold = FredProvider(cache_dir=str(tmp_path))
            snap = cold.get_snapshot(["SPX"], d(2026, 2, 1))
            assert snap.closes("SPX")[-1] == 5010.0
        finally:
            prov._http_get = original


# ----------------------------------------------------------------------
# Regime skills (recurring-play distillation)
# ----------------------------------------------------------------------
class TestRegimeSkills:
    def _ledger_with_resolutions(self, outcomes):
        led = DecisionLedger()
        for i, item in enumerate(outcomes):
            outcome, conf = (item, 0.5) if isinstance(item, bool) else item
            led.append("resolution", date(2025, 1, 1) + timedelta(days=i), {
                "symbol": "X", "agent": "judge",
                "prob_up": 0.70, "outcome": outcome,
                "confidence": conf, "regime": "calm",
                "skill_kind": "committee",
            })
        return led

    def test_distill_counts_hits_and_misses(self):
        from aletheia.agents.skills import RegimeSkillBook
        book = RegimeSkillBook()
        led = self._ledger_with_resolutions(
            [True, True, True, False, False, True] * 10  # 60 obs, 40 hits
        )
        n = book.distill(led)
        assert n == 60
        st = book.stats[("calm", "hi")]
        assert st.n == 60
        assert st.hits == 40  # 4 Trues per 6-cycle × 10 cycles

    def test_abstentions_excluded(self):
        from aletheia.agents.skills import RegimeSkillBook
        book = RegimeSkillBook()
        led2 = DecisionLedger()
        day0 = date(2025, 1, 1)
        for i, (outcome, conf) in enumerate([(True, 0.5)] * 10 + [(True, 0.0)] * 5):
            led2.append("resolution", day0 + timedelta(days=i), {
                "symbol": "X", "agent": "judge", "prob_up": 0.7,
                "outcome": outcome, "confidence": conf,
                "regime": "calm", "skill_kind": "committee",
            })
        n = book.distill(led2)
        assert n == 10  # abstentions (confidence 0) are not skill evidence

    def test_small_sample_never_fires(self):
        from aletheia.agents.skills import RegimeSkillBook
        book = RegimeSkillBook(shrinkage_n=30)
        led = self._ledger_with_resolutions([True] * 5)  # 5/5 but tiny
        book.distill(led)
        st = book.stats[("calm", "hi")]
        # shrunk: (5 + 0.5*30)/(5+30) = 0.5 -> below any decision bar+gap
        assert st.shrunk_hit_rate(0.5, 30) < 0.58

    def test_strong_history_fires_with_shift(self):
        from aletheia.agents.skills import RegimeSkillBook
        from aletheia.core.types import Bar, MarketSnapshot
        book = RegimeSkillBook(decision_bar=0.56, shrinkage_n=30)
        led = self._ledger_with_resolutions([True, True, True, False] * 25)  # 75% hits
        book.distill(led)
        bars = [Bar("X", date(2025, 1, 1) + timedelta(days=i), 100 + i,
                    100 + i, 100 + i, 100 + i, 0.0) for i in range(80)]
        snap = MarketSnapshot(as_of=date(2025, 3, 1), bars={"X": bars}, macro={})
        rec = book.recall(snap, "X", 0.70)
        assert rec is not None
        assert rec["shrunk_hit_rate"] > 0.58
        assert rec["suggested_shift"] > 0

    def test_engine_distills_and_respects_toggle(self):
        """Distillation runs during the loop; disabling kills skill entries.

        Whether a skill actually *fires* is data-dependent (it needs a
        shrunk hit rate above the bar), so we assert learning happened,
        not that a nudge occurred.
        """
        from aletheia.data.providers import SyntheticProvider
        from aletheia.core.constitution import Constitution
        from aletheia.engine.backtest import DecisionEngine, EngineConfig
        from datetime import timedelta

        provider = SyntheticProvider(seed=42, n_days=900)
        led = DecisionLedger()
        e = DecisionEngine(provider, ["SYN"], Constitution(),
                           EngineConfig(rebalance_every=5, horizon_days=21), led)
        start = date(2019, 1, 2) + timedelta(days=20)
        e.run(start, start + timedelta(days=700))
        assert e.committee.skills.to_ledger_payload()["total_observations"] > 0

        led2 = DecisionLedger()
        p2 = SyntheticProvider(seed=42, n_days=900)
        e2 = DecisionEngine(p2, ["SYN"], Constitution(),
                            EngineConfig(rebalance_every=5, horizon_days=21,
                                         skills_enabled=False), led2)
        e2.run(start, start + timedelta(days=700))
        assert not any(en.kind == "skill" for en in led2.entries)
