"""Calibration scoring and track-record trust weighting.

The committee's influence is earned, not assigned: each agent's weight is
a function of its historical forecast calibration, shrunk toward the
prior while sample size is small. This is the mechanism that makes the
committee *learn who to trust* — an agent that says "80%" and is right
80% of the time gains influence over one that is confidently wrong.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional, Sequence


def brier_score(prob: float, outcome: bool) -> float:
    return (prob - (1.0 if outcome else 0.0)) ** 2


def log_score(prob: float, outcome: bool, eps: float = 1e-9) -> float:
    p = min(max(prob, eps), 1.0 - eps)
    return -math.log(p if outcome else 1.0 - p)


@dataclass
class CalibrationRecord:
    """Aggregate calibration stats for one forecaster."""
    name: str
    n: int = 0
    brier_sum: float = 0.0
    log_sum: float = 0.0
    # reliability curve: bucket prob into deciles
    bucket_hits: list[float] = field(default_factory=lambda: [0.0] * 10)
    bucket_n: list[int] = field(default_factory=lambda: [0] * 10)

    def add(self, prob: float, outcome: bool) -> None:
        self.n += 1
        self.brier_sum += brier_score(prob, outcome)
        self.log_sum += log_score(prob, outcome)
        b = min(9, max(0, int(prob * 10)))
        self.bucket_n[b] += 1
        if outcome:
            self.bucket_hits[b] += 1.0

    @property
    def mean_brier(self) -> float:
        return self.brier_sum / self.n if self.n else float("nan")

    @property
    def mean_log(self) -> float:
        return self.log_sum / self.n if self.n else float("nan")

    def calibration_curve(self) -> list[tuple[float, float, int]]:
        """(mean predicted prob, realized frequency, count) per decile bucket."""
        out = []
        for b in range(10):
            if self.bucket_n[b] > 0:
                out.append((
                    (b + 0.5) / 10.0,
                    self.bucket_hits[b] / self.bucket_n[b],
                    self.bucket_n[b],
                ))
        return out

    def ece(self) -> float:
        """Expected calibration error across populated deciles."""
        if not self.n:
            return float("nan")
        total = 0.0
        for b in range(10):
            if self.bucket_n[b]:
                emp = self.bucket_hits[b] / self.bucket_n[b]
                pred = (b + 0.5) / 10.0
                total += (self.bucket_n[b] / self.n) * abs(emp - pred)
        return total


def trust_weight(
    record: CalibrationRecord,
    prior_weight: float = 1.0,
    shrinkage_n: int = 25,
    floor: float = 0.10,
    ceiling: float = 3.0,
) -> float:
    """Trust weight from calibration track record.

    Maps mean Brier score to a multiplier around 1.0, shrunk toward the
    prior while n is small (Bayesian-flavored damping). A perfect
    forecaster (Brier 0) earns `ceiling`; a useless one (Brier >= 0.5)
    earns `floor`. Log score is used as a tiebreaker penalty for
    overconfident extremes.
    """
    if record.n == 0:
        return prior_weight
    raw = 0.5 - record.mean_brier          # in [-0.5, 0.5]
    w = floor + (ceiling - floor) * max(0.0, raw) / 0.5
    damp = record.n / (record.n + shrinkage_n)
    return prior_weight + (w - prior_weight) * damp


@dataclass
class TrustModel:
    """Holds per-agent calibration records and computes weights.

    `names` must cover every forecasting member (including optional ones
    like "llm") so no agent's weight depends on accidental record order.
    """
    names: Sequence[str]
    records: dict[str, CalibrationRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for n in self.names:
            self.records.setdefault(n, CalibrationRecord(name=n))
    def record_forecast(self, agent: str, prob: float, outcome: bool) -> None:
        """Grade one resolved forecast and update the agent's record."""
        if agent not in self.records:
            self.records[agent] = CalibrationRecord(name=agent)
        self.records[agent].add(prob, outcome)

    def normalize(self, raw: dict[str, float]) -> dict[str, float]:
        """Turn trust multipliers into weights that sum to 1."""
        vals = {n: max(1e-6, raw.get(n, 1.0)) for n in self.records}
        total = sum(vals.values())
        return {n: v / total for n, v in vals.items()}

    def weights(self) -> dict[str, float]:
        return {n: trust_weight(r) for n, r in self.records.items()}
