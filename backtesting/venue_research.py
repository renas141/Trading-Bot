"""Fixed broker transfer check on seen development years; no holdout selection."""

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.config.settings import Settings
from app.database.repository import Repository
from app.domain import TradingMode
from app.exchange.bitvavo import BitvavoAdapter
from app.market_data.datasets import load_dataset, write_json
from app.strategies.trend_breakout import TrendBreakoutStrategy
from backtesting.benchmarks import benchmarks
from backtesting.candidate_research import make_candidate
from backtesting.net_reward_research import code_hashes, json_value, run_case, sha

VERSION = "bitvavo-transfer-development-v1"
NAMES = ("net_reward", "slow_breakout", "trend_pullback")


def instrument(path):
    meta = json.loads((path / "snapshot.json").read_text())
    raw = (path / "instrument.raw").read_bytes()
    if (meta["provider"] != "Bitvavo" or meta["market"] != "BTC-EUR"
            or sha(path / "instrument.raw") != meta["sha256"]["instrument.raw"]):
        raise ValueError("Invalid instrument evidence")
    market = BitvavoAdapter(lambda _: raw, lambda: datetime.fromisoformat(meta["instrument_requested_at"])).instrument()
    if market.status != "trading" or market.fee_category != "A":
        raise ValueError("This protocol requires trading EUR category A")
    return market


def cases(market):
    base = Settings(mode=TradingMode.BACKTEST, timeframe="4h", paper_fee_rate=Decimal("0.0025"),
                    paper_slippage_bps=Decimal("5"), paper_spread_bps=Decimal("10"),
                    price_tick=market.tick_size, quantity_step=market.quantity_step,
                    min_order_notional=market.minimum_notional, min_order_quantity=market.minimum_quantity)
    return {"bitvavo_current": base, "bitvavo_stress": replace(base, paper_fee_rate=Decimal("0.005"),
                                               paper_slippage_bps=Decimal("10"), paper_spread_bps=Decimal("20"))}


def definition(market):
    return json_value({"years": [2023, 2024], "timeframe": "4h", "symbol": "BTC/EUR",
        "variants": {name: asdict((TrendBreakoutStrategy() if name == "net_reward" else make_candidate(name)).parameters)
                     for name in NAMES}, "settings": {k: asdict(v) for k, v in cases(market).items()},
        "purpose": "Transfer existing fixed hypotheses to actual Bitvavo candles. Seen development years, no parameter tuning or holdout permission.",
        "rules": ["No 2025 data or evaluation. No candidate selection from this comparison.",
                  "All three fixed variants use the same net reward/risk >=1 guard.",
                  "Current category-A taker costs and instrument limits on old prices are a counterfactual, not the historic fee schedule.",
                  "No maker fills. Fixed spread/slippage assumptions, not a historical order-book replay.",
                  "Net profit positive in both years and both costs is only a consistency check, not a strategy release.",
                  "Separate 1000 EUR accounts per year/case, never concatenate annual returns.",
                  "No synthetic candles; complete Bitvavo source coverage is required."]})


def inputs(dataset, snapshot):
    candles, manifest = load_dataset(dataset)
    if (manifest["source"]["provider"] != "Bitvavo" or manifest["timeframe"] != "4h"
            or manifest["start"] != "2023-01-01T00:00:00+00:00"
            or manifest["end"] != "2025-01-01T00:00:00+00:00"):
        raise ValueError("Requires exactly Bitvavo 2023/2024 development data")
    return candles, manifest, instrument(snapshot)


def freeze(output, dataset, snapshot):
    _, _, market = inputs(dataset, snapshot)
    protocol = {"protocol_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version.split()[0], "definition": definition(market),
                "input_manifest_sha256": sha(dataset / "manifest.json"),
                "instrument_snapshot_sha256": sha(snapshot / "snapshot.json"), "code_sha256": code_hashes()}
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    for relative, expected in protocol["code_sha256"].items():
        source = root / relative
        if sha(source) != expected:
            raise ValueError("Code changed during freeze")
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    write_json(output / "protocol.json", protocol)


def verify(path, dataset, snapshot):
    protocol = json.loads(path.read_text())
    candles, manifest, market = inputs(dataset, snapshot)
    if (protocol["protocol_version"] != VERSION or protocol["definition"] != definition(market)
            or protocol["python_version"] != sys.version.split()[0] or protocol["code_sha256"] != code_hashes()
            or protocol["input_manifest_sha256"] != sha(dataset / "manifest.json")
            or protocol["instrument_snapshot_sha256"] != sha(snapshot / "snapshot.json")
            or any(sha(path.parent / "source" / p) != digest for p, digest in protocol["code_sha256"].items())):
        raise ValueError("Frozen sources differ")
    return protocol, candles, manifest, market


def evaluate(path, dataset, snapshot):
    protocol, candles, manifest, market = verify(path, dataset, snapshot)
    digest = sha(path)
    output = path.parent / "evaluation"
    output.mkdir(exist_ok=False)
    write_json(output / "input.json", {"manifest": manifest, "instrument": json.loads((snapshot / "snapshot.json").read_text())})
    segments = []
    with Repository(output / "research.sqlite3") as repo:
        for year in (2023, 2024):
            selected = tuple(c for c in candles if c.timestamp.year == year)
            runs, references = [], {}
            for cost, settings in cases(market).items():
                references[cost] = benchmarks(selected, settings)
                for name in NAMES:
                    assumptions = {"protocol_sha256": digest, "input_sha256": manifest["sha256"]["candles.csv"],
                                   "provider": "Bitvavo", "cost_scenario": cost, "year": year, "phase": "development",
                                   "variant": name, "settings": json_value(asdict(settings)),
                                   "parameters": protocol["definition"]["variants"][name]}
                    strategy = TrendBreakoutStrategy() if name == "net_reward" else make_candidate(name)
                    run = run_case(selected, settings, "net_reward", repo, assumptions, strategy=strategy)
                    run["variant"] = name
                    runs.append(run)
                    write_json(output / f"{year}_{name}_{cost}.json", run)
                    print(f"{year}/{name}/{cost}: {run['performance']['trades']} trades, {run['performance']['net_profit']} EUR", flush=True)
            segments.append({"name": str(year), "start": selected[0].timestamp.isoformat(), "end": selected[-1].closed_at.isoformat(),
                             "runs": runs, "benchmarks": references})
    verify(path, dataset, snapshot)
    if digest != sha(path):
        raise ValueError("Protocol changed")
    checks = {name: all(Decimal(r["performance"]["net_profit"]) > 0 for s in segments for r in s["runs"]
                       if r["variant"] == name) for name in NAMES}
    result = json_value({"protocol_sha256": digest, "input_sha256": manifest["sha256"]["candles.csv"],
                         "phase": "development", "segments": segments, "positive_all_cases": checks,
                         "screen_passed": False, "holdout_note": "Broker-Vergleich auf bekannten Entwicklungsjahren. Daraus folgt keine Holdout- oder Handelsfreigabe; 2025 bleibt reserviert."})
    write_json(output / "results.json", result)
    lines = ["# Bitvavo: Übertragung der drei festen Hypothesen", "", result["holdout_note"], "",
             "Eigene BTC/EUR-Kurse von Bitvavo; aktuelle Gebühren und Instrumentgrenzen auf historischen Preisen.",
             "0,25 % Taker je Seite, Stress 0,50 %; Spread/Slippage normal 10/5 Basispunkte, Stress 20/10.",
             "Aktueller Tick 1 EUR und Mindestmenge laut eingefrorenem Instrumentbeleg. Keine Behauptung historischer Handelsregeln.", "",
             "| Jahr | Variante | Kosten | Trades | Netto EUR | Drawdown % |", "| --- | --- | --- | ---: | ---: | ---: |"]
    for segment in segments:
        for run in segment["runs"]:
            p = run["performance"]
            lines.append(f"| {segment['name']} | {run['variant']} | {run['cost_scenario']} | {p['trades']} | {Decimal(p['net_profit']):.2f} | {Decimal(p['max_drawdown'])*100:.2f} |")
    lines += ["", "Positive Nettoergebnisse in allen vier Fällen: " + json.dumps(checks),
              "Auch ein Bestehen dieser Konsistenzprüfung wäre kein unabhängiger Nachweis. Alle Parameter stammen unverändert aus den vorherigen Studien."]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    write_json(output / "completion.json", {"results_sha256": sha(output / "results.json"), "completed_at": datetime.now(timezone.utc).isoformat()})
    return result


def main():
    parser = argparse.ArgumentParser(description="Fixed Bitvavo development comparison")
    parser.add_argument("command", choices=("freeze", "evaluate"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Experiment directory")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.output, args.dataset, args.snapshot)
    else:
        evaluate(args.output / "protocol.json", args.dataset, args.snapshot)


if __name__ == "__main__":
    main()
