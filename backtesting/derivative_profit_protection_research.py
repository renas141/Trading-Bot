"""Limited post-holdout development: two causal profit-protection policies."""

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
from backtesting.derivatives import DerivativeBacktester, ProfitProtection

VERSION = "perpetual-profit-protection-development-v1"
CANDIDATES = {
    "fixed_3r_control": None,
    "breakeven_after_1r": ProfitProtection(Decimal("1"), Decimal("0")),
    "lock_1r_after_2r": ProfitProtection(Decimal("2"), Decimal("1")),
}
CODE_FILES = (
    "app/domain.py", "app/market_data/models.py", "app/market_data/quality.py",
    "app/market_data/candles.py", "app/market_data/kraken_futures.py",
    "app/indicators/core.py", "app/strategies/base.py", "app/strategies/models.py",
    "app/strategies/regime_breakout.py", "app/strategies/long_regime.py",
    "app/derivatives/models.py", "app/derivatives/settings.py", "app/derivatives/risk.py",
    "app/derivatives/broker.py", "backtesting/derivatives.py",
    "backtesting/derivative_research.py", "backtesting/derivative_profit_protection_research.py",
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
        "development_years": [2023, 2024, 2025],
        "next_reserved_period": "2026-01-01 onward; not downloaded before selection",
        "hypothesis": "A close-confirmed profit-protection stop prevents large favorable excursions from reverting to full losses and reduces funding exposure.",
        "provenance": "Formed after the failed 2025 holdout showed losing trades with observed favorable excursions near 2.58R and 1.89R.",
        "candidates": {
            "fixed_3r_control": None,
            "breakeven_after_1r": {"trigger_r": "1", "locked_r": "0"},
            "lock_1r_after_2r": {"trigger_r": "2", "locked_r": "1"},
        },
        "cost_scenarios": ["current_conservative", "stress"], "cases": cases,
        "selection": "Eligible in every year and cost: positive net, drawdown <10%, >=3 trades, zero liquidations, max leverage <=10. Select highest worst-year stress net; alphabetical tie-break. No fallback outside these three.",
        "rules": [
            "2023-2025 are now seen development data; this study is not independent evidence.",
            "Only stop management differs. Entry, initial stop, 3R target, risk, leverage, costs and funding stay fixed.",
            "A trigger uses a completed trade-candle close and the new stop is active from the next candle only.",
            "Never test the new stop against the low of its calculation candle and never loosen a stop.",
            "Break-even means entry price before future exit costs. Gap exits receive the worse open.",
            "Exactly two management policies plus unchanged control; no parameter sweep or post-result edit.",
            "The selected rule, if any, must be frozen before any 2026 performance evaluation.",
            "No PAPER or LIVE activation from development results.",
        ],
    }


def _load(datasets):
    all_trade, all_mark, manifests = [], [], []
    for dataset in datasets:
        trade, mark, manifest = load_futures_dataset(dataset)
        all_trade.extend(trade)
        all_mark.extend(mark)
        manifests.append(manifest)
    trade = tuple(sorted(all_trade, key=lambda c: c.timestamp))
    mark = tuple(sorted(all_mark, key=lambda c: c.timestamp))
    if tuple(c.timestamp for c in trade) != tuple(c.timestamp for c in mark):
        raise ValueError("Combined trade/mark development data is not aligned")
    if not trade or trade[0].timestamp.year != 2023 or trade[-1].timestamp.year != 2025:
        raise ValueError("Development inputs must cover 2023 through 2025")
    return trade, mark, manifests


def freeze(output: Path, datasets: list[Path], parent_holdout: Path):
    if output.exists():
        raise ValueError("Use a new research directory")
    parent_results = parent_holdout.parent / "evaluation/results.json"
    if (not parent_results.is_file()
            or json.loads(parent_results.read_text())["assessment"]["holdout_passed"] is not False):
        raise ValueError("The failed completed 2025 holdout is required")
    _, _, manifests = _load(datasets)
    protocol = {
        "protocol_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0], "definition": definition(),
        "code_sha256": code_hashes(),
        "inputs": [{"manifest_sha256": sha(path / "manifest.json"),
                    "trade_sha256": manifest["sha256"]["trade.csv"],
                    "mark_sha256": manifest["sha256"]["mark.csv"]}
                   for path, manifest in zip(datasets, manifests)],
        "parent_holdout_protocol_sha256": sha(parent_holdout),
        "parent_holdout_results_sha256": sha(parent_results),
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


def read_protocol(path: Path, datasets: list[Path]):
    protocol = json.loads(path.read_text())
    if (protocol.get("protocol_version") != VERSION or protocol.get("python_version") != sys.version.split()[0]
            or protocol.get("definition") != definition() or protocol.get("code_sha256") != code_hashes()):
        raise ValueError("Frozen profit-protection protocol or source differs")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen source snapshot differs")
    trade, mark, manifests = _load(datasets)
    inputs = [{"manifest_sha256": sha(dataset / "manifest.json"),
               "trade_sha256": manifest["sha256"]["trade.csv"],
               "mark_sha256": manifest["sha256"]["mark.csv"]}
              for dataset, manifest in zip(datasets, manifests)]
    if inputs != protocol["inputs"]:
        raise ValueError("Development inputs differ")
    return protocol, trade, mark


def assess(runs):
    indexed = {(r["year"], r["candidate"], r["scenario"]): r for r in runs}
    candidates = {}
    for candidate in CANDIDATES:
        checks, stressed = {}, []
        for year in (2023, 2024, 2025):
            for scenario in ("current_conservative", "stress"):
                p = indexed[year, candidate, scenario]["performance"]
                checks[f"{year}/{scenario}"] = {
                    "positive_net": Decimal(p["net_profit"]) > 0,
                    "drawdown_below_10_percent": Decimal(p["max_drawdown"]) < Decimal("0.10"),
                    "enough_trades": p["trades"] >= 3,
                    "no_liquidation": p["liquidations"] == 0,
                    "leverage_within_cap": p["maximum_leverage_used"] <= 10,
                }
                if scenario == "stress":
                    stressed.append(Decimal(p["net_profit"]))
        candidates[candidate] = {"checks": checks, "eligible": all(all(v.values()) for v in checks.values()),
                                 "worst_stress_net": str(min(stressed))}
    eligible = [name for name, value in candidates.items() if value["eligible"]]
    selected = sorted(eligible, key=lambda name: (-Decimal(candidates[name]["worst_stress_net"]), name))[0] if eligible else None
    return {"candidates": candidates, "selected": selected, "screen_passed": selected is not None}


def render_report(result):
    lines = ["# Gewinnschutz nach dem fehlgeschlagenen 2025-Holdout", "",
             "2023-2025 sind vollständig gesehene Entwicklungsdaten. Die Auswahl ist keine unabhängige Bestätigung.", "",
             "| Jahr | Regel | Fall | Trades | Netto USD | Max. DD | Funding | Updates |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for run in result["runs"]:
        p = run["performance"]
        lines.append(f"| {run['year']} | {run['candidate']} | {run['scenario']} | {p['trades']} | {Decimal(p['net_profit']):.2f} | {Decimal(p['max_drawdown'])*100:.2f}% | {Decimal(p['funding_paid']):.2f} | {run['stop_updates']} |")
    selected = result["assessment"]["selected"] or "keine"
    lines += ["", f"Auswahl: {selected}.",
              "Eine Auswahl darf ausschließlich in einem vorab eingefrorenen 2026-Vorwärtstest weiterlaufen.",
              "LIVE bleibt gesperrt."]
    return "\n".join(lines) + "\n"


def evaluate(path: Path, datasets: list[Path]):
    protocol, trade, mark = read_protocol(path, datasets)
    output = path.parent / "evaluation"
    output.mkdir(exist_ok=False)
    runs = []
    for year in (2023, 2024, 2025):
        year_trade = tuple(c for c in trade if c.timestamp.year == year)
        year_mark = tuple(c for c in mark if c.timestamp.year == year)
        for candidate, protection in CANDIDATES.items():
            for scenario in ("current_conservative", "stress"):
                configured, funding = settings(scenario, 10)
                replay = DerivativeBacktester(
                    LongOnlyRegimeStrategy(), configured, funding, protection,
                ).run(year_trade, year_mark)
                run = {"year": year, "candidate": candidate, "scenario": scenario,
                       "candles": replay.candles_processed, "signals": replay.signals,
                       "entries": replay.entries, "rejected_entries": replay.rejected_entries,
                       "stop_updates": replay.stop_updates,
                       "performance": replay.performance.as_dict()}
                runs.append(run)
                write_json(output / f"{year}_{candidate}_{scenario}.json", run)
                print(f"{year}/{candidate}/{scenario}: trades={replay.performance.trades}, net={replay.performance.net_profit}", flush=True)
    assessment = assess(runs)
    result = json_value({"protocol_sha256": sha(path), "runs": runs, "assessment": assessment,
                         "next_period_note": "2026 remains unevaluated for this strategy selection."})
    if read_protocol(path, datasets)[0] != protocol:
        raise ValueError("Profit-protection protocol changed during evaluation")
    write_json(output / "results.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_json(output / "completion.json", {"results_sha256": sha(output / "results.json"),
                                             "completed_at": datetime.now(timezone.utc).isoformat()})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Frozen causal profit-protection development")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--dataset", type=Path, action="append", required=True)
    prepare.add_argument("--parent-holdout", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dataset", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            freeze(args.output, args.dataset, args.parent_holdout)
        else:
            evaluate(args.protocol, args.dataset)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Profit-protection research failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
