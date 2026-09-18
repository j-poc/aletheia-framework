"""Aletheia CLI.

    python -m aletheia.cli backtest --synthetic
    python -m aletheia.cli backtest --start 2018-09-01 --end 2026-08-31
    python -m aletheia.cli ablation --synthetic
    python -m aletheia.cli verify-ledger --path run_ledger.jsonl
    python -m aletheia.cli report --path run_ledger.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from aletheia.core.constitution import Constitution


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _market_args(args: argparse.Namespace):
    """Resolve (provider, symbols, start, end) from CLI flags."""
    from aletheia.data.providers import FredProvider, SyntheticProvider

    if args.synthetic:
        provider = SyntheticProvider(seed=args.seed)
        symbols = ["SYN"]
        start = date(2019, 1, 2) + timedelta(days=20)
        end = start + timedelta(days=1200)
    else:
        provider = FredProvider(cache_dir=args.cache)
        symbols = ["SPX", "NDX"]
        end = args.end or date.today() - timedelta(days=30)
        start = args.start or (end - timedelta(days=365 * 8))
    return provider, symbols, start, end


def cmd_backtest(args: argparse.Namespace) -> int:
    from aletheia.calibration.ledger import DecisionLedger
    from aletheia.engine.backtest import DecisionEngine, EngineConfig

    provider, symbols, start, end = _market_args(args)
    ledger = DecisionLedger()
    engine = DecisionEngine(
        provider=provider, symbols=symbols,
        constitution=Constitution(),
        config=EngineConfig(rebalance_every=args.rebalance_every),
        ledger=ledger,
    )
    try:
        report = engine.run(start, end)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2))
    if args.ledger_out:
        ledger.to_jsonl(args.ledger_out)
        ok, why = ledger.verify()
        print(f"ledger: {len(ledger.entries)} entries → {args.ledger_out} "
              f"(integrity: {'OK' if ok else f'BROKEN: {why}'})")
    return 0


def cmd_ablation(args: argparse.Namespace) -> int:
    from aletheia.engine.backtest import run_ablation

    provider, symbols, start, end = _market_args(args)
    rows = {}
    for variant, disable in [
        ("full_system", []),
        ("no_falsification_gate", ["falsification"]),
        ("no_trust_weighting", ["trust"]),
        ("no_constitution", ["constitution"]),
    ]:
        rows[variant] = run_ablation(provider, symbols, start, end, disable)

    print(f"{'variant':<24}{'return':>9}{'sharpe':>9}{'maxDD':>9}"
          f"{'vetoes':>8}{'brier':>8}{'ledger':>8}")
    for name, r in rows.items():
        print(f"{name:<24}"
              f"{r['total_return']:>9.1%}"
              f"{r['sharpe']:>9.2f}"
              f"{r['max_drawdown']:>9.1%}"
              f"{r['n_vetoes']:>8}"
              f"{str(r['mean_brier_all']):>8}"
              f"{'ok' if r['ledger_valid'] else 'BAD':>8}")
    return 0


def cmd_verify_ledger(args: argparse.Namespace) -> int:
    from aletheia.calibration.ledger import DecisionLedger

    try:
        ledger = DecisionLedger.from_jsonl(args.path)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    ok, why = ledger.verify()
    kinds: dict[str, int] = {}
    for e in ledger.entries:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    print(f"entries: {len(ledger.entries)}  integrity: {'OK' if ok else f'BROKEN: {why}'}")
    for k, n in sorted(kinds.items()):
        print(f"  {k:<12} {n}")
    return 0 if ok else 1


def cmd_report(args: argparse.Namespace) -> int:
    from aletheia.calibration.ledger import DecisionLedger
    from aletheia.observability import full_report

    try:
        ledger = DecisionLedger.from_jsonl(args.path)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    rep = full_report(ledger)
    if args.json:
        print(json.dumps(rep, indent=2))
        return 0
    print(f"ledger: {rep['ledger_entries']} entries (integrity: "
          f"{'OK' if rep['ledger_valid'] else 'BROKEN'})")
    print()
    print("Vetoes by article:")
    for clause, n in rep["vetoes"]["by_clause"].items():
        print(f"  Art. {clause}: {n:>4}  e.g. {rep['vetoes']['samples'][clause][:70]}")
    ev = rep["trust_evolution"]
    if ev:
        print()
        print("Trust evolution (normalized weights at milestones):")
        for snap in ev[:: max(1, len(ev) // 8)][:8]:
            w = snap["weights"]
            print(f"  {snap['as_of']}  quant={w['quant']:.3f} bull={w['bull']:.3f} "
                  f"bear={w['bear']:.3f} judge={w['judge']:.3f}")
    print()
    sk = rep["skills"]
    print(f"Skill book: {sk['n_skills']} live skills, "
          f"{sk['total_observations']} graded observations")
    for s in sk["top"][:5]:
        print(f"  ({s['regime']}, {s['bucket']}): "
              f"{s['hits']}/{s['n']} hits -> shrunk {s['shrunk_hit_rate']:.0%}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aletheia")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_market_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--synthetic", action="store_true",
                        help="offline synthetic market")
        sp.add_argument("--start", type=_parse_date, default=None)
        sp.add_argument("--end", type=_parse_date, default=None)
        sp.add_argument("--rebalance-every", type=int, default=5)
        sp.add_argument("--seed", type=int, default=7)
        sp.add_argument("--cache", default=".cache/fred")

    b = sub.add_parser("backtest", help="run the committee walk-forward")
    add_market_flags(b)
    b.add_argument("--ledger-out", default=None)
    b.set_defaults(func=cmd_backtest)

    a = sub.add_parser("ablation", help="compare full system vs ablations")
    add_market_flags(a)
    a.set_defaults(func=cmd_ablation)

    v = sub.add_parser("verify-ledger", help="verify a ledger file's integrity")
    v.add_argument("--path", required=True)
    v.set_defaults(func=cmd_verify_ledger)

    r = sub.add_parser("report", help="observability report replayed from a ledger")
    r.add_argument("--path", required=True)
    r.add_argument("--json", action="store_true", help="emit raw JSON")
    r.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
