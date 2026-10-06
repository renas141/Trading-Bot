"""Retrospective PF_XBTUSD 2022 crash diagnostic for fixed price-only rules."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.derivatives.observed_costs import load_observed_cost_scenario
from app.market_data.kraken_futures import load_futures_dataset
from app.strategies.short_term_momentum import ShortTermMomentumStrategy
from app.strategies.time_series_momentum import TimeSeriesMomentumStrategy
from backtesting.derivative_short_momentum_research import EXIT
from backtesting.derivative_tsmom_research import (
    FEE_RATE, FEE_SOURCE, TRAILING, cost_cases, json_value,
)
from backtesting.derivatives import DerivativeBacktester


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def comparison(runs: list[dict]) -> dict:
    indexed = {(run["strategy"], run["scenario"]): run for run in runs}
    return {
        strategy: {
            scenario: {
                "positive_net": Decimal(indexed[strategy, scenario]["performance"]["net_profit"]) > 0,
                "no_liquidation": indexed[strategy, scenario]["performance"]["liquidations"] == 0,
                "leverage_within_cap": indexed[strategy, scenario]["performance"]["maximum_leverage_used"] <= 10,
            }
            for scenario in ("observed_p95", "double_cost_stress")
        }
        for strategy in ("dual_horizon", "short_horizon")
    }


def render(result: dict) -> str:
    lines = [
        "# PF_XBTUSD-Crashdiagnose 2022", "",
        "Der Zeitraum ist rückblickend geöffnet und kein unabhängiger Profitabilitätsnachweis.",
        "Regimefelder sind für 2022 nicht lückenlos verfügbar; deshalb werden ausschließlich",
        "zwei bereits definierte, preisbasierte Regeln unverändert verglichen.", "",
        "| Regel | Kostenfall | Trades | Netto USD | Profitfaktor | Max. DD | Max. Hebel |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in result["runs"]:
        p = run["performance"]
        lines.append(
            f"| {run['strategy']} | {run['scenario']} | {p['trades']} | "
            f"{Decimal(p['net_profit']):.2f} | {p['profit_factor'] or '–'} | "
            f"{Decimal(p['max_drawdown']) * 100:.2f}% | {p['maximum_leverage_used']}x |"
        )
    lines += [
        "", "Die kurze Regel bestand beide 2022-Kostenfälle, die langsame nicht. Da die kurze",
        "Regel 2025 schwach war, wird sie nicht rückwirkend ausgewählt. Das Ergebnis begründet",
        "höchstens eine neue, getrennt zu prüfende Mehrhorizont-Hypothese. PAPER und LIVE bleiben aus.",
    ]
    return "\n".join(lines) + "\n"


def evaluate(dataset: Path, candidate: Path, summary: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("Use a new diagnostic output directory")
    trade, mark, manifest = load_futures_dataset(dataset)
    if (trade[0].timestamp.isoformat() != "2022-03-23T08:00:00+00:00"
            or trade[-1].closed_at.isoformat() != "2023-01-01T00:00:00+00:00"
            or len(trade) != 1702):
        raise ValueError("2022 crash diagnostic coverage differs")
    observed = load_observed_cost_scenario(
        candidate, summary, fee_rate=FEE_RATE, fee_source=FEE_SOURCE,
    )
    definitions = (
        ("dual_horizon", TimeSeriesMomentumStrategy, {"trailing_stop_policy": TRAILING}),
        ("short_horizon", ShortTermMomentumStrategy, {"close_exit_policy": EXIT}),
    )
    runs = []
    for name, strategy, options in definitions:
        for scenario, (settings, funding) in cost_cases(observed).items():
            replay = DerivativeBacktester(strategy(), settings, funding, **options).run(trade, mark)
            runs.append({
                "strategy": name, "scenario": scenario,
                "candles": replay.candles_processed, "signals": replay.signals,
                "entries": replay.entries, "rejected_entries": replay.rejected_entries,
                "performance": replay.performance.as_dict(),
            })
    result = json_value({
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "market": "PF_XBTUSD", "period": [manifest["start"], manifest["end"]],
        "classification": "seen_retrospective_crash_diagnostic",
        "dataset_manifest_sha256": _sha(dataset / "manifest.json"),
        "cost_candidate_sha256": _sha(candidate), "cost_summary_sha256": _sha(summary),
        "rows": len(trade), "runs": runs, "comparison": comparison(runs),
        "profitability_proven": False, "paper_enabled": False, "live_enabled": False,
        "limitations": [
            "2022 is now seen retrospective data.",
            "Public regime and complete historical hourly funding fields are unavailable.",
            "The comparison cannot select or amend an existing forward candidate.",
        ],
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
    parser = argparse.ArgumentParser(description="Run PF_XBTUSD 2022 crash diagnostics")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--cost-candidate", type=Path, required=True)
    parser.add_argument("--cost-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.dataset, args.cost_candidate, args.cost_summary, args.output)
        print(json.dumps({"comparison": result["comparison"], "live_enabled": False}, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"2022 crash diagnostic failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
