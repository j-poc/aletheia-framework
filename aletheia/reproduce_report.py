"""Recompute the research report's market matrix from the local FRED cache.

Usage: PYTHONDONTWRITEBYTECODE=1 python3 -m aletheia.reproduce_report
The printed JSON is research evidence, not a live trading result.
"""
from __future__ import annotations

import json
import hashlib
import math
import random
import statistics
from datetime import date
from pathlib import Path

from aletheia.core.constitution import Constitution
from aletheia.data.providers import FRED_MAP, FredProvider
from aletheia.engine.backtest import DecisionEngine, EngineConfig


def metrics(curve: list[float]) -> dict[str, float]:
    daily = [b / a - 1 for a, b in zip(curve, curve[1:])]
    sd = statistics.pstdev(daily) if len(daily) > 1 else 0.0
    peak = curve[0]
    drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    return {
        "total_return": round(curve[-1] / curve[0] - 1, 4),
        "sharpe": round(statistics.mean(daily) / sd * math.sqrt(252), 2) if sd else 0.0,
        "max_drawdown": round(drawdown, 4),
    }


def sharpe_interval(curve: list[float], seed: int = 7) -> list[float]:
    """Stationary bootstrap of daily returns, mean block length 21 sessions."""
    returns = [b / a - 1 for a, b in zip(curve, curve[1:])]
    n = len(returns)
    rng = random.Random(seed)
    scores = []
    for _ in range(2_000):
        i = rng.randrange(n)
        sample = []
        for _ in range(n):
            if rng.random() < 1 / 21:
                i = rng.randrange(n)
            sample.append(returns[i])
            i = (i + 1) % n
        sd = statistics.pstdev(sample)
        scores.append(statistics.mean(sample) / sd * math.sqrt(252) if sd else 0.0)
    scores.sort()
    return [round(scores[49], 2), round(scores[1949], 2)]


def baselines(provider, symbols, end, active_dates):
    full = provider.get_snapshot(symbols, end, lookback=100_000)
    prices = {s: {b.date: b.close for b in full.bars[s]} for s in symbols}
    starts = {s: prices[s][active_dates[0]] for s in symbols}
    latest = dict(starts)
    index_curve = [1.0]
    for day in active_dates[1:]:
        for s in symbols:
            latest[s] = prices[s].get(day, latest[s])
        index_curve.append(statistics.mean(
            latest[s] / starts[s]
            for s in symbols
        ))
    fixed_curve = [1 + 0.25 * (value - 1) for value in index_curve]
    return {"buy_and_hold": metrics(index_curve), "fixed_25pct": metrics(fixed_curve)}


def pinned_provider(cache_dir: Path = Path(".cache/fred")) -> FredProvider:
    """Load only the source bytes used for the published matrix."""
    manifest = json.loads((Path(__file__).resolve().parent.parent /
                           "data/source_manifest.json").read_text())
    provider = FredProvider(cache_dir=str(cache_dir))
    for series, source in manifest["series"].items():
        path = cache_dir / source["file"]
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"missing pinned input {path}; see data/source_manifest.json"
            ) from exc
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise RuntimeError(f"pinned input hash mismatch: {path}")
        provider._memory[series] = FredProvider._parse_csv(
            FRED_MAP[series], raw.decode("utf-8")
        )
    return provider


def main() -> None:
    provider = pinned_provider()
    variants = {
        "full": {},
        "no_context": {"context_enabled": False},
        "no_macro": {"macro_enabled": False},
        "no_skills": {"skills_enabled": False},
        "v3": {"context_enabled": False, "macro_enabled": False,
               "skills_enabled": False},
    }
    cases = {
        "SPX+NDX": (["SPX", "NDX"], date(2018, 9, 1), date(2026, 8, 31)),
        "DJIA": (["DJIA"], date(2018, 9, 1), date(2026, 8, 31)),
        "Nikkei": (["NIKKEI"], date(2018, 9, 1), date(2026, 8, 31)),
        "Nikkei 1990-2017": (["NIKKEI"], date(1990, 1, 1), date(2017, 12, 31)),
    }
    out = {}
    for name, (symbols, start, end) in cases.items():
        full = provider.get_snapshot(symbols, end, lookback=100_000)
        dates = [b.date for b in full.bars[symbols[0]] if start <= b.date <= end][60:]
        rows = {}
        for variant, flags in variants.items():
            if name == "Nikkei 1990-2017" and variant not in ("full", "no_skills"):
                continue
            engine = DecisionEngine(provider, symbols, Constitution(), EngineConfig(**flags))
            report = engine.run(start, end)
            rows[variant] = report
            if variant == "full":
                rows[variant]["sharpe_95pct_bootstrap"] = sharpe_interval(
                    [engine.cfg.initial_capital] + [v for _, v in engine.equity_curve]
                )
        out[name] = {
            "active_start": dates[0].isoformat(),
            "active_end": dates[-1].isoformat(),
            "system": rows,
            "baselines": baselines(provider, symbols, end, dates),
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
