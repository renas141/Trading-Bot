"""One-shot 2025 holdout for the selected long-only perpetual hypothesis."""

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.market_data.datasets import write_json
from app.market_data.kraken_futures import load_futures_dataset
from app.strategies.long_regime import LongOnlyRegimeStrategy
from backtesting.derivative_research import json_value, settings, sha
from backtesting.derivatives import DerivativeBacktester

VERSION = "perpetual-long-bias-holdout-v1"
CODE_FILES = (
    "app/domain.py", "app/market_data/models.py", "app/market_data/quality.py",
    "app/market_data/candles.py", "app/market_data/kraken_futures.py",
    "app/indicators/core.py", "app/strategies/base.py", "app/strategies/models.py",
    "app/strategies/regime_breakout.py", "app/strategies/long_regime.py",
    "app/derivatives/models.py", "app/derivatives/settings.py", "app/derivatives/risk.py",
    "app/derivatives/broker.py", "backtesting/derivatives.py",
    "backtesting/derivative_research.py", "backtesting/derivative_long_research.py",
    "backtesting/derivative_holdout.py",
)


def code_hashes():
    root = Path(__file__).resolve().parents[1]
    return {name: sha(root / name) for name in CODE_FILES}


def definition():
    cases = {}
    for scenario in ("current_conservative", "stress"):
        configured, funding = settings(scenario, 10)
        cases[scenario] = {"settings": json_value(asdict(configured)),
                           "funding_rate_per_4h": str(funding)}
    return {
        "market": "PF_XBTUSD", "symbol": "BTC/USD", "timeframe": "4h",
        "start": "2025-01-01T00:00:00+00:00", "end": "2026-01-01T00:00:00+00:00",
        "selected_strategy": "long_only_regime_breakout_perpetual/0.1.0",
        "cost_scenarios": ["current_conservative", "stress"], "cases": cases,
        "source": {"provider": "Kraken Futures", "tick_types": ["trade", "mark"],
                   "endpoint": "https://futures.kraken.com/api/charts/v1/:tick_type/PF_XBTUSD/4h"},
        "gate": "In BOTH cases: net profit > 0, max drawdown <10%, at least 3 trades, zero liquidations, max leverage <=10.",
        "rules": [
            "This protocol is frozen before the 2025 PF_XBTUSD candles are downloaded or evaluated.",
            "Evaluate the selected long-only v2 strategy exactly once; no controls, tuning or fallback.",
            "Use only complete aligned 4h trade and mark candles for the half-open 2025 UTC year.",
            "Use the same in-year warm-up, execution, adverse funding, risk and cost assumptions as development.",
            "A pass is evidence for continued PAPER validation, not permission for LIVE trading.",
            "A failure rejects this strategy version; do not reinterpret or rerun 2025.",
        ],
    }


def freeze(output: Path, parent: Path):
    if output.exists():
        raise ValueError("Use a new holdout directory")
    parent_results = parent.parent / "evaluation/results.json"
    if not parent_results.is_file() or json.loads(parent_results.read_text())["assessment"]["screen_passed"] is not True:
        raise ValueError("A passed completed v2 development gate is required")
    protocol = {
        "protocol_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0], "definition": definition(),
        "code_sha256": code_hashes(), "parent_protocol_sha256": sha(parent),
        "parent_results_sha256": sha(parent_results),
    }
    output.mkdir(parents=True)
    try:
        root = Path(__file__).resolve().parents[1]
        for relative, expected in protocol["code_sha256"].items():
            source = root / relative
            if sha(source) != expected:
                raise ValueError("Source changed during holdout freeze")
            target = output / "source" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        write_json(output / "protocol.json", protocol)
    except BaseException:
        shutil.rmtree(output)
        raise


def read_protocol(path: Path):
    protocol = json.loads(path.read_text())
    if (protocol.get("protocol_version") != VERSION or protocol.get("python_version") != sys.version.split()[0]
            or protocol.get("definition") != definition() or protocol.get("code_sha256") != code_hashes()):
        raise ValueError("Frozen holdout protocol or source differs")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen holdout source snapshot differs")
    return protocol


def assess(runs):
    checks = {}
    for run in runs:
        p = run["performance"]
        checks[run["scenario"]] = {
            "positive_net": Decimal(p["net_profit"]) > 0,
            "drawdown_below_10_percent": Decimal(p["max_drawdown"]) < Decimal("0.10"),
            "enough_trades": p["trades"] >= 3,
            "no_liquidation": p["liquidations"] == 0,
            "leverage_within_cap": p["maximum_leverage_used"] <= 10,
        }
    return {"checks": checks, "holdout_passed": len(checks) == 2 and all(all(v.values()) for v in checks.values())}


def render_report(result):
    lines = ["# Einmalige 2025-Perpetual-Holdout-Prüfung", "",
             "Diese Ergebnisse wurden genau einmal mit der vorab festgelegten Long-only-Strategie erzeugt.", "",
             "| Kosten/Funding | Trades | Netto USD | Rendite | Max. DD | Profitfaktor | Funding | Liquidationen | Max. Hebel |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for run in result["runs"]:
        p = run["performance"]
        factor = p["profit_factor"] if p["profit_factor"] is not None else "n/a"
        lines.append(f"| {run['scenario']} | {p['trades']} | {Decimal(p['net_profit']):.2f} | {Decimal(p['return_fraction'])*100:.2f}% | {Decimal(p['max_drawdown'])*100:.2f}% | {factor} | {Decimal(p['funding_paid']):.2f} | {p['liquidations']} | {p['maximum_leverage_used']}x |")
    lines += ["", f"Holdout bestanden: {'ja' if result['assessment']['holdout_passed'] else 'nein'}.",
              "Auch ein bestandener Holdout garantiert keine künftigen Gewinne. Vor echtem Kapital sind längere PAPER-Beobachtung, vollständige Funding-Daten und Broker-/Kontoprüfung nötig.",
              "LIVE bleibt gesperrt."]
    return "\n".join(lines) + "\n"


def evaluate(path: Path, dataset: Path):
    protocol = read_protocol(path)
    output = path.parent / "evaluation"
    if output.exists():
        raise ValueError("Holdout was already evaluated")
    trade, mark, manifest = load_futures_dataset(dataset)
    definition_value = protocol["definition"]
    if (manifest["market_id"] != definition_value["market"] or manifest["start"] != definition_value["start"]
            or manifest["end"] != definition_value["end"] or len(trade) != 2190 or len(mark) != 2190):
        raise ValueError("Holdout dataset does not exactly cover 2025")
    output.mkdir()
    write_json(output / "input.json", {"manifest_sha256": sha(dataset / "manifest.json"),
                                       "trade_sha256": manifest["sha256"]["trade.csv"],
                                       "mark_sha256": manifest["sha256"]["mark.csv"], "manifest": manifest})
    runs = []
    for scenario in definition_value["cost_scenarios"]:
        configured, funding = settings(scenario, 10)
        replay = DerivativeBacktester(LongOnlyRegimeStrategy(), configured, funding).run(trade, mark)
        run = {"scenario": scenario, "candles": replay.candles_processed,
               "signals": replay.signals, "entries": replay.entries,
               "rejected_entries": replay.rejected_entries,
               "performance": replay.performance.as_dict()}
        runs.append(run)
        write_json(output / f"2025_{scenario}.json", run)
        print(f"2025/{scenario}: trades={replay.performance.trades}, net={replay.performance.net_profit}", flush=True)
    result = json_value({"protocol_sha256": sha(path), "input_manifest_sha256": sha(dataset / "manifest.json"),
                         "runs": runs, "assessment": assess(runs)})
    if read_protocol(path) != protocol:
        raise ValueError("Holdout protocol changed during evaluation")
    write_json(output / "results.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_json(output / "completion.json", {"results_sha256": sha(output / "results.json"),
                                             "completed_at": datetime.now(timezone.utc).isoformat()})


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-shot 2025 perpetual holdout")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--parent", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            freeze(args.output, args.parent)
        else:
            evaluate(args.protocol, args.dataset)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Holdout failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
