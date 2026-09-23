"""Preregistered v2: result-informed long-only structural bias versus symmetric v1."""

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
from app.strategies.regime_breakout import RegimeBreakoutStrategy
from backtesting.derivative_research import json_value, settings, sha
from backtesting.derivatives import DerivativeBacktester

VERSION = "perpetual-long-bias-development-v2"
CODE_FILES = (
    "app/domain.py", "app/market_data/models.py", "app/market_data/quality.py",
    "app/market_data/candles.py", "app/market_data/kraken_futures.py",
    "app/indicators/core.py", "app/strategies/base.py", "app/strategies/models.py",
    "app/strategies/regime_breakout.py", "app/strategies/long_regime.py",
    "app/derivatives/models.py", "app/derivatives/settings.py", "app/derivatives/risk.py",
    "app/derivatives/broker.py", "backtesting/derivatives.py",
    "backtesting/derivative_research.py", "backtesting/derivative_long_research.py",
)


def code_hashes():
    root = Path(__file__).resolve().parents[1]
    return {name: sha(root / name) for name in CODE_FILES}


def definition():
    strategy = LongOnlyRegimeStrategy()
    cases = {}
    for scenario in ("current_conservative", "stress"):
        configured, funding = settings(scenario, 10)
        cases[scenario] = {"settings": json_value(asdict(configured)),
                           "funding_rate_per_4h": str(funding)}
    return {
        "market": "PF_XBTUSD", "symbol": "BTC/USD", "timeframe": "4h",
        "development_years": [2023, 2024], "reserved_holdout_year": 2025,
        "hypothesis": "Suppress countertrend perpetual shorts because Bitcoin has a persistent structural long bias.",
        "provenance": "This hypothesis was formed after v1 showed 2024 losses and four short trades; it is development-only and data-informed.",
        "strategy": {"name": strategy.name, "version": strategy.version,
                     "parameters": json_value(asdict(strategy.parameters))},
        "variants": ["symmetric_dynamic_10x", "long_only_dynamic_10x"],
        "cost_scenarios": ["current_conservative", "stress"], "cases": cases,
        "primary": "long_only_dynamic_10x",
        "gate": {
            "each_year_each_cost": "net_profit > 0, max_drawdown < 10%, liquidations == 0, at least 3 trades",
            "comparison": "long-only must not underperform symmetric v1 in any matched case",
            "leverage": "maximum observed leverage <= 10",
        },
        "rules": [
            "Only SHORT suppression changes from v1; all entry filters, exits, costs, funding and risk remain fixed.",
            "2023/2024 remain seen development data; this comparison is not independent evidence.",
            "At least three completed trades per year/cost is only a feasibility floor, not statistical significance.",
            "Signals execute next bar; stops use trade price; liquidations use mark price; adverse funding is never zero.",
            "Risk stays at 1% per trade and leverage is the smallest required value up to 10x.",
            "No parameter sweep or fallback selection. 2025 remains unopened unless the exact gate passes.",
            "No automatic PAPER or LIVE activation.",
        ],
    }


def freeze(output: Path, dataset: Path, parent: Path):
    if output.exists():
        raise ValueError("Use a new research directory")
    parent_results = parent.parent / "evaluation/results.json"
    if not parent_results.is_file():
        raise ValueError("Completed v1 results are required")
    parent_value = json.loads(parent_results.read_text())
    if parent_value["assessment"]["screen_passed"] is not False:
        raise ValueError("v2 is only justified by the failed v1 gate")
    _, _, manifest = load_futures_dataset(dataset)
    protocol = {
        "protocol_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0], "definition": definition(),
        "code_sha256": code_hashes(), "input_manifest_sha256": sha(dataset / "manifest.json"),
        "input_trade_sha256": manifest["sha256"]["trade.csv"],
        "input_mark_sha256": manifest["sha256"]["mark.csv"],
        "parent_protocol_sha256": sha(parent), "parent_results_sha256": sha(parent_results),
    }
    output.mkdir(parents=True)
    try:
        root = Path(__file__).resolve().parents[1]
        for relative, expected in protocol["code_sha256"].items():
            source = root / relative
            if sha(source) != expected:
                raise ValueError("Source changed during freeze")
            target = output / "source" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        write_json(output / "protocol.json", protocol)
    except BaseException:
        shutil.rmtree(output)
        raise


def read_protocol(path: Path, dataset: Path):
    protocol = json.loads(path.read_text())
    if (protocol.get("protocol_version") != VERSION or protocol.get("python_version") != sys.version.split()[0]
            or protocol.get("definition") != definition() or protocol.get("code_sha256") != code_hashes()
            or protocol.get("input_manifest_sha256") != sha(dataset / "manifest.json")):
        raise ValueError("Frozen v2 protocol, source or input differs")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen v2 source snapshot differs")
    trade, mark, manifest = load_futures_dataset(dataset)
    if (protocol["input_trade_sha256"] != manifest["sha256"]["trade.csv"]
            or protocol["input_mark_sha256"] != manifest["sha256"]["mark.csv"]):
        raise ValueError("Input candle checksums differ")
    return protocol, trade, mark


def assess(runs):
    indexed = {(r["year"], r["variant"], r["scenario"]): r for r in runs}
    checks = {}
    for year in (2023, 2024):
        for scenario in ("current_conservative", "stress"):
            primary = indexed[year, "long_only_dynamic_10x", scenario]["performance"]
            control = indexed[year, "symmetric_dynamic_10x", scenario]["performance"]
            checks[f"{year}/{scenario}"] = {
                "positive_net": Decimal(primary["net_profit"]) > 0,
                "drawdown_below_10_percent": Decimal(primary["max_drawdown"]) < Decimal("0.10"),
                "enough_trades": primary["trades"] >= 3,
                "no_liquidation": primary["liquidations"] == 0,
                "leverage_within_cap": primary["maximum_leverage_used"] <= 10,
                "not_worse_than_symmetric": Decimal(primary["net_profit"]) >= Decimal(control["net_profit"]),
            }
    return {"checks": checks, "screen_passed": all(all(v.values()) for v in checks.values())}


def render_report(result):
    lines = ["# Perpetual Long-only-Strukturhypothese", "",
             "Diese zweite Hypothese entstand nach dem Fehlschlag von v1 und ist deshalb ausdrücklich ergebnisinformierte Entwicklung, keine unabhängige Bestätigung.", "",
             "| Jahr | Variante | Kosten/Funding | Trades | Netto USD | Max. DD | Long | Short | Max. Hebel |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for run in result["runs"]:
        p = run["performance"]
        lines.append(f"| {run['year']} | {run['variant']} | {run['scenario']} | {p['trades']} | {Decimal(p['net_profit']):.2f} | {Decimal(p['max_drawdown'])*100:.2f}% | {p['long_trades']} | {p['short_trades']} | {p['maximum_leverage_used']}x |")
    lines += ["", f"Gate bestanden: {'ja' if result['assessment']['screen_passed'] else 'nein'}.",
              result["holdout_note"], "", "LIVE bleibt gesperrt."]
    return "\n".join(lines) + "\n"


def evaluate(path: Path, dataset: Path):
    protocol, trade, mark = read_protocol(path, dataset)
    output = path.parent / "evaluation"
    output.mkdir(exist_ok=False)
    runs = []
    variants = (("symmetric_dynamic_10x", RegimeBreakoutStrategy),
                ("long_only_dynamic_10x", LongOnlyRegimeStrategy))
    for year in (2023, 2024):
        year_trade = tuple(c for c in trade if c.timestamp.year == year)
        year_mark = tuple(c for c in mark if c.timestamp.year == year)
        for variant, factory in variants:
            for scenario in ("current_conservative", "stress"):
                configured, funding = settings(scenario, 10)
                replay = DerivativeBacktester(factory(), configured, funding).run(year_trade, year_mark)
                run = {"year": year, "variant": variant, "scenario": scenario,
                       "candles": replay.candles_processed, "signals": replay.signals,
                       "entries": replay.entries, "rejected_entries": replay.rejected_entries,
                       "performance": replay.performance.as_dict()}
                runs.append(run)
                write_json(output / f"{year}_{variant}_{scenario}.json", run)
                print(f"{year}/{variant}/{scenario}: trades={replay.performance.trades}, net={replay.performance.net_profit}", flush=True)
    assessment = assess(runs)
    note = ("Das Entwicklungstor ist bestanden; eine einmalige separate 2025-Prüfung darf vorbereitet werden."
            if assessment["screen_passed"] else "Das Entwicklungstor ist nicht bestanden; 2025 bleibt ungeöffnet.")
    result = json_value({"protocol_sha256": sha(path), "input_manifest_sha256": sha(dataset / "manifest.json"),
                         "runs": runs, "assessment": assessment, "holdout_note": note})
    if read_protocol(path, dataset)[0] != protocol:
        raise ValueError("v2 protocol changed during evaluation")
    write_json(output / "results.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_json(output / "completion.json", {"results_sha256": sha(output / "results.json"),
                                             "completed_at": datetime.now(timezone.utc).isoformat()})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Frozen long-only perpetual development research")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--dataset", type=Path, required=True)
    prepare.add_argument("--parent", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            freeze(args.output, args.dataset, args.parent)
        else:
            evaluate(args.protocol, args.dataset)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Long-only research failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
