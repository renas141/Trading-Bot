"""Retrospective 2026 diagnostic for the already-fixed regime momentum rule."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.derivatives.observed_costs import load_observed_cost_scenario
from app.market_data.kraken_futures import load_futures_dataset
from app.market_data.kraken_perpetual_regime_history import load_dataset as load_regime_dataset
from app.market_data.perpetual_regime_alignment import align_futures_regime
from app.strategies.regime_confirmed_momentum import RegimeConfirmedMomentumStrategy
from backtesting.derivative_regime_momentum_research import (
    EXIT, FEE_RATE, FEE_SOURCE, cost_cases, json_value,
)
from backtesting.derivatives import DerivativeBacktester


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_directions(trades) -> dict:
    grouped = defaultdict(lambda: {"trades": 0, "wins": 0, "net_profit": Decimal("0")})
    for trade in trades:
        row = grouped[trade.position.direction.value]
        row["trades"] += 1
        row["wins"] += trade.net_pnl > 0
        row["net_profit"] += trade.net_pnl
    return json_value(dict(grouped))


def render(result: dict) -> str:
    lines = [
        "# PF_XBTUSD-Regimediagnose 2026", "",
        "Diese Periode wurde am 05.10.2026 bewusst als gesehene Entwicklungsperiode geöffnet.",
        "Sie ist kein unabhängiger Profitabilitätsnachweis und verändert keinen laufenden Forward-Test.", "",
        "| Kostenfall | Trades | Netto USD | Profitfaktor | Max. DD | LONG | SHORT | Max. Hebel |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in result["runs"]:
        p, d = run["performance"], run["directions"]
        lines.append(
            f"| {run['scenario']} | {p['trades']} | {Decimal(p['net_profit']):.2f} | "
            f"{p['profit_factor'] or '–'} | {Decimal(p['max_drawdown']) * 100:.2f}% | "
            f"{d.get('LONG', {}).get('trades', 0)} | {d.get('SHORT', {}).get('trades', 0)} | "
            f"{p['maximum_leverage_used']}x |"
        )
    lines += [
        "", "Die Richtungsergebnisse wechseln zwischen den Jahren. Deshalb wird weder LONG noch SHORT",
        "auf Basis dieser rückblickenden Diagnose pauschal deaktiviert. Funding wird als bereits",
        "festgelegte adverse Sensitivität modelliert, weil Kraken für diese Periode keine lückenlose",
        "öffentliche stündliche Funding-Reihe geliefert hat. LIVE bleibt aus.",
    ]
    return "\n".join(lines) + "\n"


def evaluate(price_path: Path, regime_path: Path, candidate: Path, summary: Path,
             output: Path) -> dict:
    if output.exists():
        raise ValueError("Use a new diagnostic output directory")
    trade, mark, price_manifest = load_futures_dataset(price_path)
    regime, regime_manifest = load_regime_dataset(regime_path)
    aligned = align_futures_regime(trade, mark, regime)
    if (not aligned or aligned[0].trade.timestamp.isoformat() != "2026-01-01T00:00:00+00:00"
            or aligned[-1].trade.closed_at.isoformat() != "2026-09-24T12:00:00+00:00"):
        raise ValueError("2026 diagnostic coverage differs")
    observed = load_observed_cost_scenario(
        candidate, summary, fee_rate=FEE_RATE, fee_source=FEE_SOURCE,
    )
    runs = []
    for scenario, (settings, funding) in cost_cases(observed).items():
        replay = DerivativeBacktester(
            RegimeConfirmedMomentumStrategy(aligned), settings, funding,
            close_exit_policy=EXIT,
        ).run(tuple(bar.trade for bar in aligned), tuple(bar.mark for bar in aligned))
        runs.append({
            "scenario": scenario, "candles": replay.candles_processed,
            "signals": replay.signals, "entries": replay.entries,
            "rejected_entries": replay.rejected_entries,
            "performance": replay.performance.as_dict(),
            "directions": summarize_directions(replay.trades),
        })
    result = json_value({
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "market": "PF_XBTUSD", "period": "2026-01-01/2026-09-24T12:00Z",
        "classification": "seen_retrospective_development",
        "price_manifest_sha256": _sha(price_path / "manifest.json"),
        "regime_manifest_sha256": _sha(regime_path / "manifest.json"),
        "cost_candidate_sha256": _sha(candidate),
        "cost_summary_sha256": _sha(summary),
        "input_rows": {"trade": len(trade), "mark": len(mark), "regime": len(regime)},
        "runs": runs,
        "profitability_proven": False, "paper_enabled": False, "live_enabled": False,
        "limitations": [
            "The period is seen development data and cannot validate the rule independently.",
            "Historical quote-level spread/slippage is unavailable; observed p95 and doubled costs are modeled.",
            "Historical hourly funding was incomplete; the preregistered adverse sensitivity is used.",
        ],
        "source_ranges": {
            "prices": [price_manifest["start"], price_manifest["end"]],
            "regime": [regime_manifest["start"], regime_manifest["end"]],
        },
    })
    output.mkdir(parents=True)
    try:
        (output / "results.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (output / "report.md").write_text(render(result), encoding="utf-8")
    except BaseException:
        shutil.rmtree(output)
        raise
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the seen 2026 PF_XBTUSD diagnostic")
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--regime", type=Path, required=True)
    parser.add_argument("--cost-candidate", type=Path, required=True)
    parser.add_argument("--cost-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.prices, args.regime, args.cost_candidate,
                          args.cost_summary, args.output)
        print(json.dumps({"runs": result["runs"], "live_enabled": False}, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"2026 regime diagnostic failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
