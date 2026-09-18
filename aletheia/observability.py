"""Ledger-native observability: replay the decision ledger.

Everything Aletheia decides is already in the hash-chained ledger, so
observability is a *replay*, not a parallel telemetry pipeline — the same
philosophy behind Vercel's agent observability, applied to a governed
investment committee.

Reports:
* trust-weight evolution over the run (who earned influence, when)
* veto breakdown by article (which clauses bind, how hard)
* skill book summary (which recurring plays are live, with support)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional


def trust_evolution(ledger) -> list[dict]:
    """Recompute normalized trust weights at every resolution date.

    Replays resolutions in ledger order, applying the same shrinkage the
    TrustModel uses, and snapshots the weights — showing how influence
    migrated between agents over the life of the run.
    """
    from aletheia.calibration.trust import CalibrationRecord, trust_weight

    # Derive the member roster from the ledger itself, so optional
    # members (e.g. the LLM member) appear without a hardcoded list.
    agents: list[str] = []
    for e in ledger.entries:
        if e.kind != "resolution":
            continue
        a = e.payload.get("agent")
        if a and a not in agents:
            agents.append(a)
    records = {a: CalibrationRecord(name=a) for a in agents}
    out: list[dict] = []
    for e in ledger.entries:
        if e.kind != "resolution":
            continue
        p = e.payload
        agent, conf = p.get("agent"), p.get("confidence", 1.0)
        if not agent or conf <= 0 or agent not in records:
            continue
        records[agent].add(p["prob_up"], p["outcome"])
        raw = {a: trust_weight(r) for a, r in records.items()}
        total = sum(max(1e-6, v) for v in raw.values())
        out.append({
            "as_of": e.as_of,
            "n": {a: r.n for a, r in records.items()},
            "weights": {a: round(v / total, 4) for a, v in raw.items()},
        })
    # dedupe consecutive snapshots (same day, similar weights)
    deduped: list[dict] = []
    for snap in out:
        if deduped and snap["as_of"] == deduped[-1]["as_of"] and snap["n"] == deduped[-1]["n"]:
            continue
        deduped.append(snap)
    return deduped


def veto_breakdown(ledger) -> dict:
    """Veto counts by constitutional article, with a sample reason each."""
    counts: dict[str, int] = defaultdict(int)
    samples: dict[str, str] = {}
    for e in ledger.entries:
        if e.kind != "veto":
            continue
        clause = e.payload.get("clause", "?")
        counts[clause] += 1
        samples.setdefault(clause, e.payload.get("reason", ""))
    return {
        "total": sum(counts.values()),
        "by_clause": dict(sorted(counts.items())),
        "samples": samples,
    }


def skill_summary(ledger) -> dict:
    """Final state of the regime skill book, as learned from the ledger."""
    from aletheia.agents.skills import RegimeSkillBook

    book = RegimeSkillBook()
    book.distill(ledger)
    return book.to_ledger_payload()


def full_report(ledger) -> dict:
    return {
        "ledger_entries": len(ledger.entries),
        "ledger_valid": ledger.verify()[0],
        "trust_evolution": trust_evolution(ledger),
        "vetoes": veto_breakdown(ledger),
        "skills": skill_summary(ledger),
    }
