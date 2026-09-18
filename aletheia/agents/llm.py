"""LLM committee member: a model's opinion as a gradeable forecast.

An LLM can join the committee through the exact same contract as the
built-in agents: it emits a pre-registered, probabilistic, gradeable
`Forecast` (committed before evidence review), is graded net-of-cost and
trust-weighted exactly like everyone else, and — the part that makes
frontier models governable — every failure mode (missing key, network
error, timeout, malformed output, out-of-range probability) resolves to
an explicit **abstention**, never an exception and never a fabricated
number. A silent, confidently wrong LLM earns nothing and influences
nothing; the trust model does the rest.

Boundary discipline (deliberate, not incidental):

* `LlmConfig.from_env` is the ONLY place env vars are parsed.
* `build_prompt` and `parse_llm_json` are pure functions: structured
  snapshot state in → prompt string out; raw text in → `ParsedCall` or
  an abstention reason out. No I/O, no clocks, no environment.
* `_completion` (stdlib urllib) is the only code that can raise, and the
  member's `forecast` maps every exception to an abstention.
* The endpoint is OpenAI-compatible (`/chat/completions`) and configured
  entirely via environment variables:

      ALETHEIA_LLM_API_KEY   (required; absent -> member abstains)
      ALETHEIA_LLM_BASE_URL  (default https://api.openai.com/v1)
      ALETHEIA_LLM_MODEL     (default gpt-4o-mini)

Walk-forward safety: the prompt contains only bars with date <= the
decision date and macro readings the provider already clipped to that
date — the member can no more see the future than the built-ins can.
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from aletheia.core.types import (
    Forecast,
    MarketSnapshot,
    abstain_forecast,
)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


# --------------------------------------------------------------------------
# Boundary: configuration
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class LlmConfig:
    """Endpoint configuration for the OpenAI-compatible chat API."""
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None) -> Optional["LlmConfig"]:
        """Parse config from environment. Returns None when no key is set.

        This is the single boundary where env vars are read; everything
        downstream receives typed config and trusts it.
        """
        environ = env if env is not None else dict(os.environ)
        key = environ.get("ALETHEIA_LLM_API_KEY", "").strip()
        if not key:
            return None
        return cls(
            api_key=key,
            base_url=environ.get("ALETHEIA_LLM_BASE_URL", "").strip() or DEFAULT_BASE_URL,
            model=environ.get("ALETHEIA_LLM_MODEL", "").strip() or DEFAULT_MODEL,
        )


# --------------------------------------------------------------------------
# Pure transforms: prompt construction and response parsing
# --------------------------------------------------------------------------
def build_prompt(
    snapshot: MarketSnapshot,
    symbol: str,
    horizon_days: int,
    member_names: list[str],
) -> str:
    """Structured state -> JSON prompt. Point-in-time data only.

    Bars are filtered to `date <= snapshot.as_of` (defense in depth: the
    provider already clips, but the prompt must be safe regardless of
    provider), and each numeric field is explicitly typed/rounded.
    """
    px = [
        round(b.close, 4) for b in snapshot.bars.get(symbol, [])
        if b.date <= snapshot.as_of
    ]
    rets = snapshot.returns(symbol, 63)
    vol_ann = None
    if len(rets) >= 20:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        vol_ann = round((var ** 0.5) * (252 ** 0.5), 4)
    payload = {
        "symbol": symbol,
        "as_of": snapshot.as_of.isoformat(),
        "horizon_days": horizon_days,
        "prices": px[-63:],
        "realized_vol_annualized": vol_ann,
        "macro": {k: round(float(v), 4) for k, v in sorted(snapshot.macro.items())},
        "committee_members": list(member_names),
    }
    return (
        "You are the LLM member of an investment committee. Decide whether "
        f"{symbol} will drift upward over the next {horizon_days} trading "
        "sessions, judged net of round-trip trading costs. Use only the "
        "state provided; it already ends at the decision date.\n\n"
        "STATE:\n" + json.dumps(payload, indent=2) + "\n\n"
        "Respond with ONE JSON object and nothing else:\n"
        '{"prob_up": <float 0..1>, "confidence": <float 0..1>, '
        '"expected_edge": <float>, "rationale": "<= 240 chars"}\n'
        "Guidance: confidence is your certainty in the call, not the "
        "probability itself; 0 means abstain."
    )


@dataclass(frozen=True)
class ParsedCall:
    """A validated LLM call, parsed at the boundary into domain types."""
    prob_up: float
    confidence: float
    expected_edge: float
    rationale: str


def parse_llm_json(text: str) -> tuple[Optional[ParsedCall], Optional[str]]:
    """Raw model text -> (ParsedCall, None) or (None, abstention_reason).

    Pure, total, and strict: malformed JSON, non-object payloads, missing
    or non-numeric fields, and probabilities outside (0, 1) all resolve
    to an explicit reason. No exceptions escape.
    """
    raw = (text or "").strip()
    if raw.startswith("```"):
        stripped = raw[3:]
        if stripped.lstrip().lower().startswith("json"):
            stripped = stripped.lstrip()[4:]
        raw = stripped.strip().strip("`").strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None, "malformed output: not valid JSON"
    if not isinstance(obj, dict):
        return None, "malformed output: JSON is not an object"
    prob, conf = obj.get("prob_up"), obj.get("confidence")
    if not isinstance(prob, (int, float)) or isinstance(prob, bool):
        return None, "malformed output: prob_up missing or non-numeric"
    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        return None, "malformed output: confidence missing or non-numeric"
    if not 0.0 < prob < 1.0:
        return None, f"out-of-range probability: prob_up={prob}"
    edge = obj.get("expected_edge", 0.0)
    if not isinstance(edge, (int, float)) or isinstance(edge, bool):
        edge = 0.0
    rationale = obj.get("rationale")
    rationale = rationale.strip()[:240] if isinstance(rationale, str) and rationale.strip() else "(none given)"
    return ParsedCall(
        prob_up=float(prob), confidence=float(conf),
        expected_edge=float(edge), rationale=rationale,
    ), None


def default_completion(config: LlmConfig, prompt: str, timeout: float = 30.0) -> str:
    """The one raising boundary: stdlib urllib POST to a chat completion."""
    body = json.dumps({
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{config.base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        outer = json.loads(resp.read().decode("utf-8", errors="replace"))
    return outer["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------
# The member
# --------------------------------------------------------------------------
class LlmMember:
    """An LLM as a committee member: pre-registered, graded, abstain-only.

    Drop-in with the built-in agents: `forecast()` returns a `Forecast`
    under the same contract. `completion_fn` is injectable, so tests run
    against a deterministic stub and no network is ever touched unless a
    real config exists.
    """

    def __init__(
        self,
        horizon_days: int = 21,
        config: Optional[LlmConfig] = None,
        completion_fn: Optional[Callable[[LlmConfig, str], str]] = None,
        name: str = "llm",
    ) -> None:
        self.name = name
        self.horizon_days = horizon_days
        self.config = config  # None -> unconfigured; member abstains
        self.completion_fn = completion_fn or default_completion

    # ------------------------------------------------------------------
    def forecast(self, snapshot: MarketSnapshot, symbol: str,
                 member_names: Optional[list[str]] = None) -> Forecast:

        def abstain(why: str) -> Forecast:
            return abstain_forecast(
                self.name, snapshot, symbol, self.horizon_days, why)

        if self.config is None:
            return abstain("LLM member not configured (no API key)")
        # Pre-registration: the prompt contains only point-in-time state
        # and (names of) other members — never their views. The call is
        # issued and resolved before the gate or judge sees anything, and
        # the resulting forecast is never revised afterwards.
        prompt = build_prompt(snapshot, symbol, self.horizon_days,
                              member_names or [])
        try:
            raw = self.completion_fn(self.config, prompt)
        except Exception as exc:  # noqa: BLE001 — the boundary absorbs all
            return abstain(f"LLM unavailable: {type(exc).__name__}")
        parsed, why = parse_llm_json(raw)
        if parsed is None:
            return abstain(why or "malformed output")
        return Forecast(
            symbol=symbol, horizon_days=self.horizon_days,
            prob_up=parsed.prob_up, expected_edge=parsed.expected_edge,
            confidence=max(0.0, min(1.0, parsed.confidence)),
            rationale=f"llm: {parsed.rationale}", basis={"llm": 1.0},
            issued_on=snapshot.as_of, agent=self.name,
        )
