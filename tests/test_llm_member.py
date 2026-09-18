"""LLM committee member: contract conformance, grading, abstention paths.

Every test runs against a deterministic stub completion — no network is
ever touched. The live API path is exercised only by the optional smoke
call at the bottom, which runs solely when ALETHEIA_LLM_API_KEY is set.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pytest

from aletheia.agents.llm import (
    DEFAULT_MODEL,
    LlmConfig,
    LlmMember,
    build_prompt,
    parse_llm_json,
)
from aletheia.calibration.ledger import DecisionLedger
from aletheia.calibration.trust import TrustModel
from aletheia.core.constitution import Constitution
from aletheia.core.types import Bar, Forecast, MarketSnapshot
from aletheia.data.providers import SyntheticProvider
from aletheia.engine.backtest import DecisionEngine, EngineConfig


def _call(prob=0.66, conf=0.7, edge=0.02, rationale="stub call"):
    return json.dumps({"prob_up": prob, "confidence": conf,
                       "expected_edge": edge, "rationale": rationale})


def _stub_failing(exc: Exception | None = None):
    def fn(config, prompt):
        raise exc or ConnectionError("endpoint down")
    return fn


def _snap(as_of=date(2025, 6, 2), n=80):
    bars = [Bar("X", as_of - timedelta(days=n - 1 - i),
                100 + i, 100 + i, 100 + i, 100 + i, 0.0)
            for i in range(n)]
    return MarketSnapshot(as_of=as_of, bars={"X": bars}, macro={"VIX": 15.0})


def _cfg():
    return LlmConfig(api_key="test-key",
                     base_url="https://stub.local/v1", model="stub-1")


def _member(completion_fn=None, config="default", **kw):
    if config == "default":
        config = _cfg()
    return LlmMember(horizon_days=21, config=config,
                     completion_fn=completion_fn or (lambda c, p: _call()),
                     **kw)


# --------------------------------------------------------------------------
# Boundary: configuration (env parsing happens only here)
# --------------------------------------------------------------------------
class TestLlmConfigBoundary:
    def test_no_key_returns_none(self):
        assert LlmConfig.from_env({}) is None
        assert LlmConfig.from_env({"ALETHEIA_LLM_API_KEY": "   "}) is None

    def test_key_with_defaults(self):
        cfg = LlmConfig.from_env({"ALETHEIA_LLM_API_KEY": "k"})
        assert cfg == LlmConfig(api_key="k",
                                base_url="https://api.openai.com/v1",
                                model=DEFAULT_MODEL)

    def test_overrides(self):
        cfg = LlmConfig.from_env({"ALETHEIA_LLM_API_KEY": "k",
                                  "ALETHEIA_LLM_BASE_URL": "http://x/v1 ",
                                  "ALETHEIA_LLM_MODEL": "m1"})
        assert cfg.base_url == "http://x/v1"
        assert cfg.model == "m1"


# --------------------------------------------------------------------------
# Boundary: response parsing (pure, total, strict)
# --------------------------------------------------------------------------
class TestParseBoundary:
    def test_valid_json_parses(self):
        call, why = parse_llm_json(_call())
        assert call is not None and why is None
        assert call.prob_up == 0.66

    def test_fenced_json_parses(self):
        call, why = parse_llm_json("```json\n" + _call() + "\n```")
        assert call is not None and why is None

    def test_all_malformations_resolve_to_reasons(self):
        bad = [
            "", "hello", "[1, 2]",
            '{"prob_up": "x", "confidence": 0.5}',
            '{"prob_up": 0.6}',
            _call(prob=1.0), _call(prob=0.0), _call(prob=1.5),
            _call(conf="hi"),
        ]
        for raw in bad:
            call, why = parse_llm_json(raw)
            assert call is None
            assert why  # every failure names its reason

    def test_never_raises(self):
        parse_llm_json(None)  # type: ignore[arg-type] — total function


# --------------------------------------------------------------------------
# Abstention paths: every failure is an explicit, visible non-call
# --------------------------------------------------------------------------
class TestAbstentionPaths:
    def test_unconfigured_abstains_without_touching_completion(self):
        def must_not_run(config, prompt):
            raise AssertionError("completion must not be called")
        f = _member(must_not_run, config=None).forecast(_snap(), "X")
        assert f.confidence == 0.0
        assert "not configured" in f.rationale
        assert f.agent == "llm"

    def test_network_error_abstains(self):
        f = _member(_stub_failing()).forecast(_snap(), "X")
        assert f.confidence == 0.0
        assert "LLM unavailable" in f.rationale

    def test_malformed_output_abstains(self):
        f = _member(lambda c, p: "not json at all").forecast(_snap(), "X")
        assert f.confidence == 0.0
        assert "malformed" in f.rationale

    def test_out_of_range_probability_abstains(self):
        f = _member(lambda c, p: _call(prob=1.2)).forecast(_snap(), "X")
        assert f.confidence == 0.0
        assert "out-of-range" in f.rationale

    def test_abstention_is_never_graded(self):
        tm = TrustModel(names=["llm"])
        tm.record_forecast("llm", 0.9, True)  # control: a graded call
        n_before = tm.records["llm"].n
        f = _member(_stub_failing()).forecast(_snap(), "X")
        assert f.confidence == 0.0  # engine grades only confidence > 0
        assert tm.records["llm"].n == n_before


# --------------------------------------------------------------------------
# Contract conformance: same Forecast as every other member
# --------------------------------------------------------------------------
class TestContractConformance:
    def test_valid_call_is_gradeable_forecast(self):
        f = _member().forecast(_snap(), "X")
        assert isinstance(f, Forecast)
        assert f.agent == "llm"
        assert 0.0 < f.prob_up < 1.0
        assert f.confidence > 0
        assert f.issued_on == date(2025, 6, 2)

    def test_prompt_contains_only_point_in_time_state(self):
        as_of = date(2025, 6, 2)
        snap = _snap(as_of=as_of)
        prompt = build_prompt(snap, "X", 21, ["quant", "bull", "bear"])
        # no date beyond the decision date can appear anywhere
        assert str(as_of + timedelta(days=1)) not in prompt
        assert str(as_of + timedelta(days=30)) not in prompt
        # members appear by NAME only — never their views or numbers
        state = prompt.split("STATE:")[1].split("Respond")[0]
        assert "quant" in state and "prob_up" not in state

    def test_prompt_includes_macro_and_vol(self):
        prompt = build_prompt(_snap(), "X", 21, [])
        assert "VIX" in prompt and "realized_vol_annualized" in prompt


# --------------------------------------------------------------------------
# Engine integration: graded, trust-weighted, and toggle-off by default
# --------------------------------------------------------------------------
class TestCommitteeIntegration:
    START = date(2019, 1, 2) + timedelta(days=20)

    def _engine(self, llm_member):
        provider = SyntheticProvider(seed=42, n_days=900)
        led = DecisionLedger()
        eng = DecisionEngine(provider, ["SYN"], Constitution(),
                             EngineConfig(rebalance_every=5, horizon_days=21),
                             led, llm_member=llm_member)
        return eng, led

    def test_llm_graded_and_trust_weighted(self):
        eng, led = self._engine(_member(lambda c, p: _call(prob=0.75, conf=0.8)))
        report = eng.run(self.START, self.START + timedelta(days=400))
        # graded like any member: its own calibration record fills up
        assert report["calibration"]["llm"]["n"] > 0
        # and weighted: every fused decision includes the llm in its roster
        tws = [e.payload["trust_weights"] for e in led.entries
               if e.kind == "committee"]
        assert tws and all("llm" in w for w in tws)
        # its resolutions reached the ledger under its own name
        agents = {e.payload.get("agent") for e in led.entries
                  if e.kind == "resolution"}
        assert "llm" in agents

    def test_default_run_unchanged_without_llm(self):
        provider = SyntheticProvider(seed=42, n_days=900)
        led = DecisionLedger()
        eng = DecisionEngine(provider, ["SYN"], Constitution(),
                             EngineConfig(rebalance_every=5, horizon_days=21), led)
        report = eng.run(self.START, self.START + timedelta(days=400))
        assert "llm" not in report["calibration"]
        assert not any(e.payload.get("agent") == "llm" for e in led.entries)

    def test_unkeyed_llm_abstains_end_to_end(self):
        eng, led = self._engine(LlmMember(horizon_days=21, config=None))
        report = eng.run(self.START, self.START + timedelta(days=400))
        # abstentions flow through the ledger like any forecast...
        forecasts = [e for e in led.entries if e.kind == "forecast"
                     and e.payload.get("agent") == "llm"]
        assert forecasts
        assert all("abstain" in e.payload["rationale"] for e in forecasts)
        # ...are resolved like any forecast...
        res = [e for e in led.entries if e.kind == "resolution"
               and e.payload.get("agent") == "llm"]
        assert res and all(e.payload["confidence"] == 0.0 for e in res)
        # ...but are never graded and never earn influence
        assert report["calibration"]["llm"]["n"] == 0


# --------------------------------------------------------------------------
# Optional live smoke: runs ONLY when a real key exists in the environment
# --------------------------------------------------------------------------
@pytest.mark.skipif(not os.environ.get("ALETHEIA_LLM_API_KEY"),
                    reason="no ALETHEIA_LLM_API_KEY: live path unexercised")
def test_live_smoke_call():
    """Minimal live-path proof: one real completion must produce a
    Forecast (a call or an explicit abstention — never an exception)."""
    member = LlmMember(horizon_days=21, config=LlmConfig.from_env())
    f = member.forecast(_snap(), "X")
    assert isinstance(f, Forecast)
    assert 0.0 <= f.confidence <= 1.0
