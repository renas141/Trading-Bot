"""Frozen targetless ATR-trailing development on seen perpetual data."""

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
from app.strategies.long_regime import LongOnlyRegimeStrategy, UncappedLongOnlyRegimeStrategy
from backtesting.derivative_research import json_value, settings, sha
from backtesting.derivatives import DerivativeBacktester, TrailingStopPolicy


VERSION = "perpetual-atr-trailing-development-v1"
TRAILING = TrailingStopPolicy(atr_period=42, atr_multiple=Decimal("3"))
CODE_FILES = (
    "app/domain.py", "app/market_data/models.py", "app/market_data/quality.py",
    "app/market_data/candles.py", "app/market_data/kraken_futures.py",
    "app/indicators/core.py", "app/strategies/base.py", "app/strategies/models.py",
    "app/strategies/regime_breakout.py", "app/strategies/long_regime.py",
    "app/derivatives/models.py", "app/derivatives/settings.py", "app/derivatives/risk.py",
    "app/derivatives/broker.py", "backtesting/derivatives.py",
    "backtesting/derivative_research.py", "backtesting/derivative_trailing_research.py",
)


def code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {name: sha(root / name) for name in CODE_FILES}


def definition() -> dict:
    cases = {}
    for scenario in ("current_conservative", "stress"):
        configured, funding = settings(scenario, 10)
        cases[scenario] = {"settings": json_value(asdict(configured)),
                           "adverse_funding_rate_per_4h": str(funding)}
    return {
        "market": "PF_XBTUSD", "symbol": "BTC/USD", "timeframe": "4h",
        "development_years": [2023, 2024, 2025],
        "next_reserved_period": "2026-01-01 onward; no price-performance data loaded",
        "hypothesis": (
            "A targetless long-only trend breakout with a causal 3-ATR trailing stop can "
            "capture the right tail and avoid repeated fixed-target re-entry cycles."
        ),
        "provenance": (
            "This is a structural trend-following alternative, not another threshold repair. "
            "The same targetless 3-ATR concept was preregistered in the earlier spot study "
            "and was positive in three of four Bitvavo year/cost cases."
        ),
        "variants": {
            "fixed_3r_control": {"fixed_target_r": "3", "trailing": None},
            "uncapped_atr_trailing": {
                "fixed_target_r": None, "atr_period": 42, "atr_multiple": "3",
                "anchor": "highest completed close since entry",
            },
        },
        "cost_scenarios": ["current_conservative", "stress"], "cases": cases,
        "gate": (
            "The trailing candidate must be positive in every year and cost case, have "
            "drawdown <10%, >=3 trades, zero liquidations and maximum leverage <=10. "
            "No fallback candidate."
        ),
        "rules": [
            "2023-2025 are seen development data; this study is not independent evidence.",
            "Both variants use the identical long-only entry, initial 3-ATR stop, sizing, leverage and risk limits.",
            "The trailing candidate removes the fixed target and uses highest completed close minus 3*simple ATR(42).",
            "A tighter stop becomes active only on the next candle and is never tested against an earlier low.",
            "The stop never loosens. Gaps fill at the worse next open with configured slippage and fees.",
            "Exactly one structural candidate plus unchanged control; no parameter sweep or post-result edit.",
            "Historical funding remains a nonzero adverse sensitivity in both cost cases.",
            "A passing candidate must be frozen before any 2026 price-performance evaluation. PAPER and LIVE remain disabled.",
        ],
    }


def load_inputs(datasets: list[Path]):
    trades, marks, manifests = [], [], []
    for dataset in datasets:
        trade, mark, manifest = load_futures_dataset(dataset)
        trades.extend(trade); marks.extend(mark); manifests.append(manifest)
    trade = tuple(sorted(trades, key=lambda candle: candle.timestamp))
    mark = tuple(sorted(marks, key=lambda candle: candle.timestamp))
    if tuple(c.timestamp for c in trade) != tuple(c.timestamp for c in mark):
        raise ValueError("Combined trade/mark development data is not aligned")
    if not trade or trade[0].timestamp.year != 2023 or trade[-1].timestamp.year != 2025:
        raise ValueError("Development inputs must cover 2023 through 2025")
    return trade, mark, manifests


def input_hashes(datasets: list[Path], manifests: list[dict]) -> list[dict]:
    return [{"manifest_sha256": sha(path / "manifest.json"),
             "trade_sha256": manifest["sha256"]["trade.csv"],
             "mark_sha256": manifest["sha256"]["mark.csv"]}
            for path, manifest in zip(datasets, manifests)]


def freeze(output: Path, datasets: list[Path], parent_results: Path) -> None:
    if output.exists():
        raise ValueError("Use a new research directory")
    parent = json.loads(parent_results.read_text(encoding="utf-8"))
    completion = parent_results.parent / "completion.json"
    if (parent.get("assessment", {}).get("selected") is not None or not completion.is_file()
            or json.loads(completion.read_text())["results_sha256"] != sha(parent_results)):
        raise ValueError("A completed failed re-entry study is required")
    _, _, manifests = load_inputs(datasets)
    protocol = {"protocol_version": VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version.split()[0], "definition": definition(),
                "code_sha256": code_hashes(), "inputs": input_hashes(datasets, manifests),
                "parent_results_sha256": sha(parent_results),
                "parent_completion_sha256": sha(completion)}
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
        shutil.rmtree(output); raise


def read_protocol(path: Path, datasets: list[Path]):
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if (protocol.get("protocol_version") != VERSION
            or protocol.get("python_version") != sys.version.split()[0]
            or protocol.get("definition") != definition()
            or protocol.get("code_sha256") != code_hashes()):
        raise ValueError("Frozen trailing protocol or source differs")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen source snapshot differs")
    trade, mark, manifests = load_inputs(datasets)
    if input_hashes(datasets, manifests) != protocol["inputs"]:
        raise ValueError("Development inputs differ")
    return protocol, trade, mark


def assess(runs: list[dict]) -> dict:
    indexed = {(run["year"], run["variant"], run["scenario"]): run for run in runs}
    checks = {}
    for year in (2023, 2024, 2025):
        for scenario in ("current_conservative", "stress"):
            performance = indexed[year, "uncapped_atr_trailing", scenario]["performance"]
            checks[f"{year}/{scenario}"] = {
                "positive_net": Decimal(performance["net_profit"]) > 0,
                "drawdown_below_10_percent": Decimal(performance["max_drawdown"]) < Decimal("0.10"),
                "enough_trades": performance["trades"] >= 3,
                "no_liquidation": performance["liquidations"] == 0,
                "leverage_within_cap": performance["maximum_leverage_used"] <= 10,
            }
    passed = all(all(values.values()) for values in checks.values())
    return {"primary": "uncapped_atr_trailing", "checks": checks,
            "selected": "uncapped_atr_trailing" if passed else None,
            "screen_passed": passed}


def render_report(result: dict) -> str:
    lines = ["# Unbegrenzter Trendgewinn mit ATR-Trailing-Stop", "",
             "2023-2025 sind vollständig gesehene Entwicklungsdaten. Das Ergebnis ist keine unabhängige Bestätigung.", "",
             "| Jahr | Variante | Fall | Trades | Netto USD | Max. DD | Funding | Stop-Updates |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for run in result["runs"]:
        p = run["performance"]
        lines.append(f"| {run['year']} | {run['variant']} | {run['scenario']} | {p['trades']} | "
                     f"{Decimal(p['net_profit']):.2f} | {Decimal(p['max_drawdown']) * 100:.2f}% | "
                     f"{Decimal(p['funding_paid']):.2f} | {run['stop_updates']} |")
    selected = result["assessment"]["selected"] or "keine"
    lines += ["", f"Auswahl: {selected}.",
              "Nur eine bestandene Auswahl dürfte in einen eingefrorenen 2026-Vorwärtstest.",
              "PAPER und LIVE bleiben gesperrt."]
    return "\n".join(lines) + "\n"


def evaluate(path: Path, datasets: list[Path]) -> None:
    protocol, trade, mark = read_protocol(path, datasets)
    output = path.parent / "evaluation"; output.mkdir(exist_ok=False)
    runs = []
    variants = {
        "fixed_3r_control": (LongOnlyRegimeStrategy, None),
        "uncapped_atr_trailing": (UncappedLongOnlyRegimeStrategy, TRAILING),
    }
    for year in (2023, 2024, 2025):
        year_trade = tuple(c for c in trade if c.timestamp.year == year)
        year_mark = tuple(c for c in mark if c.timestamp.year == year)
        for variant, (factory, trailing) in variants.items():
            for scenario in ("current_conservative", "stress"):
                configured, funding = settings(scenario, 10)
                replay = DerivativeBacktester(factory(), configured, funding,
                                              trailing_stop_policy=trailing).run(year_trade, year_mark)
                run = {"year": year, "variant": variant, "scenario": scenario,
                       "candles": replay.candles_processed, "signals": replay.signals,
                       "entries": replay.entries, "rejected_entries": replay.rejected_entries,
                       "stop_updates": replay.stop_updates,
                       "performance": replay.performance.as_dict()}
                runs.append(run); write_json(output / f"{year}_{variant}_{scenario}.json", run)
                print(f"{year}/{variant}/{scenario}: trades={replay.performance.trades}, "
                      f"net={replay.performance.net_profit}", flush=True)
    result = json_value({"protocol_sha256": sha(path), "runs": runs,
                         "assessment": assess(runs),
                         "next_period_note": "2026 price performance remains unevaluated."})
    if read_protocol(path, datasets)[0] != protocol:
        raise ValueError("Trailing protocol changed during evaluation")
    write_json(output / "results.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_json(output / "completion.json", {"results_sha256": sha(output / "results.json"),
                                             "completed_at": datetime.now(timezone.utc).isoformat()})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Frozen perpetual ATR trailing development")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--dataset", type=Path, action="append", required=True)
    prepare.add_argument("--parent-results", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dataset", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze": freeze(args.output, args.dataset, args.parent_results)
        else: evaluate(args.protocol, args.dataset)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Trailing research failed: {exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
