"""Limited seen-data development of two causal perpetual exit policies."""

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
from backtesting.derivatives import CloseExitPolicy, DerivativeBacktester


VERSION = "perpetual-close-exit-development-v1"
CANDIDATES = {
    "fixed_3r_control": None,
    "ten_day_time_exit": CloseExitPolicy(max_holding_bars=60),
    "three_day_losing_momentum_exit": CloseExitPolicy(
        momentum_lookback=18, minimum_holding_bars=18,
    ),
}
CODE_FILES = (
    "app/domain.py", "app/market_data/models.py", "app/market_data/quality.py",
    "app/market_data/candles.py", "app/market_data/kraken_futures.py",
    "app/indicators/core.py", "app/strategies/base.py", "app/strategies/models.py",
    "app/strategies/regime_breakout.py", "app/strategies/long_regime.py",
    "app/derivatives/models.py", "app/derivatives/settings.py", "app/derivatives/risk.py",
    "app/derivatives/broker.py", "backtesting/derivatives.py",
    "backtesting/derivative_research.py", "backtesting/derivative_exit_research.py",
)


def code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {name: sha(root / name) for name in CODE_FILES}


def definition() -> dict:
    cases = {}
    for scenario in ("current_conservative", "stress"):
        configured, funding = settings(scenario, 10)
        cases[scenario] = {
            "settings": json_value(asdict(configured)),
            "adverse_funding_rate_per_4h": str(funding),
        }
    return {
        "market": "PF_XBTUSD", "symbol": "BTC/USD", "timeframe": "4h",
        "development_years": [2023, 2024, 2025],
        "next_reserved_period": "2026-01-01 onward; no price-performance data loaded",
        "hypothesis": (
            "A causal exit for stale or failed breakouts reduces full-stop reversals and funding "
            "exposure without removing the profitable trend captures."
        ),
        "provenance": (
            "Defined after the failed 2025 holdout and profit-protection study showed one losing "
            "trade held 131 four-hour bars and no profit-protection candidate survived stress costs."
        ),
        "candidates": {
            "fixed_3r_control": None,
            "ten_day_time_exit": {"max_holding_bars": 60},
            "three_day_losing_momentum_exit": {
                "momentum_lookback": 18, "minimum_holding_bars": 18,
                "condition": "LONG close below both entry and 18-bar close mean",
            },
        },
        "cost_scenarios": ["current_conservative", "stress"], "cases": cases,
        "selection": (
            "Eligible in every year and cost: positive net, drawdown <10%, >=3 trades, "
            "zero liquidations, max leverage <=10. Select highest worst-year stress net; "
            "alphabetical tie-break. No fallback outside these three."
        ),
        "rules": [
            "2023-2025 are seen development data; this study is not independent evidence.",
            "Only the close-exit policy differs. Entries, initial stop, 3R target, risk, leverage, fees, slippage and adverse funding stay fixed.",
            "A management exit uses a completed candle and fills at the next candle open with configured adverse slippage.",
            "Intrabar stop, target and mark-price liquidation checks occur before a pending management exit at the next open.",
            "Ten days equals 60 four-hour bars. Three days equals an 18-bar lookback and minimum holding period.",
            "The momentum exit requires the position to be losing and the close to be below its 18-bar mean.",
            "Exactly two exit alternatives plus unchanged control; no parameter sweep or post-result edit.",
            "Historical funding is unavailable for these years from the public analytics endpoint, so nonzero adverse sensitivities remain in both cost cases.",
            "A selected rule must be frozen before any 2026 price-performance evaluation. PAPER and LIVE remain disabled.",
        ],
    }


def _load(datasets: list[Path]):
    all_trade, all_mark, manifests = [], [], []
    for dataset in datasets:
        trade, mark, manifest = load_futures_dataset(dataset)
        all_trade.extend(trade)
        all_mark.extend(mark)
        manifests.append(manifest)
    trade = tuple(sorted(all_trade, key=lambda candle: candle.timestamp))
    mark = tuple(sorted(all_mark, key=lambda candle: candle.timestamp))
    if tuple(c.timestamp for c in trade) != tuple(c.timestamp for c in mark):
        raise ValueError("Combined trade/mark development data is not aligned")
    if not trade or trade[0].timestamp.year != 2023 or trade[-1].timestamp.year != 2025:
        raise ValueError("Development inputs must cover 2023 through 2025")
    return trade, mark, manifests


def freeze(output: Path, datasets: list[Path], parent_results: Path) -> None:
    if output.exists():
        raise ValueError("Use a new research directory")
    parent = json.loads(parent_results.read_text(encoding="utf-8"))
    completion = parent_results.parent / "completion.json"
    if (parent.get("assessment", {}).get("selected") is not None or not completion.is_file()
            or json.loads(completion.read_text())["results_sha256"] != sha(parent_results)):
        raise ValueError("A completed failed profit-protection study is required")
    _, _, manifests = _load(datasets)
    protocol = {
        "protocol_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0], "definition": definition(),
        "code_sha256": code_hashes(),
        "inputs": [
            {"manifest_sha256": sha(path / "manifest.json"),
             "trade_sha256": manifest["sha256"]["trade.csv"],
             "mark_sha256": manifest["sha256"]["mark.csv"]}
            for path, manifest in zip(datasets, manifests)
        ],
        "parent_results_sha256": sha(parent_results),
        "parent_completion_sha256": sha(completion),
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
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if (protocol.get("protocol_version") != VERSION
            or protocol.get("python_version") != sys.version.split()[0]
            or protocol.get("definition") != definition()
            or protocol.get("code_sha256") != code_hashes()):
        raise ValueError("Frozen exit protocol or source differs")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen source snapshot differs")
    trade, mark, manifests = _load(datasets)
    inputs = [
        {"manifest_sha256": sha(dataset / "manifest.json"),
         "trade_sha256": manifest["sha256"]["trade.csv"],
         "mark_sha256": manifest["sha256"]["mark.csv"]}
        for dataset, manifest in zip(datasets, manifests)
    ]
    if inputs != protocol["inputs"]:
        raise ValueError("Development inputs differ")
    return protocol, trade, mark


def assess(runs: list[dict]) -> dict:
    indexed = {(run["year"], run["candidate"], run["scenario"]): run for run in runs}
    candidates = {}
    for candidate in CANDIDATES:
        checks, stressed = {}, []
        for year in (2023, 2024, 2025):
            for scenario in ("current_conservative", "stress"):
                performance = indexed[year, candidate, scenario]["performance"]
                checks[f"{year}/{scenario}"] = {
                    "positive_net": Decimal(performance["net_profit"]) > 0,
                    "drawdown_below_10_percent": Decimal(performance["max_drawdown"]) < Decimal("0.10"),
                    "enough_trades": performance["trades"] >= 3,
                    "no_liquidation": performance["liquidations"] == 0,
                    "leverage_within_cap": performance["maximum_leverage_used"] <= 10,
                }
                if scenario == "stress":
                    stressed.append(Decimal(performance["net_profit"]))
        eligible = all(all(values.values()) for values in checks.values())
        candidates[candidate] = {
            "checks": checks, "eligible": eligible, "worst_stress_net": str(min(stressed)),
        }
    eligible = [name for name, result in candidates.items() if result["eligible"]]
    selected = (sorted(eligible, key=lambda name: (
        -Decimal(candidates[name]["worst_stress_net"]), name,
    ))[0] if eligible else None)
    return {"candidates": candidates, "selected": selected,
            "screen_passed": selected is not None}


def render_report(result: dict) -> str:
    lines = [
        "# Zeit- und Momentum-Ausstiege nach dem fehlgeschlagenen Holdout", "",
        "2023-2025 sind vollständig gesehene Entwicklungsdaten. Das Ergebnis ist keine unabhängige Bestätigung.", "",
        "| Jahr | Regel | Fall | Trades | Netto USD | Max. DD | Funding | Ausstiege |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in result["runs"]:
        performance = run["performance"]
        lines.append(
            f"| {run['year']} | {run['candidate']} | {run['scenario']} | "
            f"{performance['trades']} | {Decimal(performance['net_profit']):.2f} | "
            f"{Decimal(performance['max_drawdown']) * 100:.2f}% | "
            f"{Decimal(performance['funding_paid']):.2f} | {run['management_exits']} |"
        )
    selected = result["assessment"]["selected"] or "keine"
    lines += ["", f"Auswahl: {selected}.",
              "Nur eine bestandene Auswahl dürfte in einen eingefrorenen 2026-Vorwärtstest.",
              "PAPER und LIVE bleiben gesperrt."]
    return "\n".join(lines) + "\n"


def evaluate(path: Path, datasets: list[Path]) -> None:
    protocol, trade, mark = read_protocol(path, datasets)
    output = path.parent / "evaluation"
    output.mkdir(exist_ok=False)
    runs = []
    for year in (2023, 2024, 2025):
        year_trade = tuple(c for c in trade if c.timestamp.year == year)
        year_mark = tuple(c for c in mark if c.timestamp.year == year)
        for candidate, policy in CANDIDATES.items():
            for scenario in ("current_conservative", "stress"):
                configured, funding = settings(scenario, 10)
                replay = DerivativeBacktester(
                    LongOnlyRegimeStrategy(), configured, funding,
                    close_exit_policy=policy,
                ).run(year_trade, year_mark)
                management_exits = sum(
                    trade.exit_reason in ("TIME_EXIT", "MOMENTUM_EXIT") for trade in replay.trades
                )
                run = {
                    "year": year, "candidate": candidate, "scenario": scenario,
                    "candles": replay.candles_processed, "signals": replay.signals,
                    "entries": replay.entries, "rejected_entries": replay.rejected_entries,
                    "management_exits": management_exits,
                    "performance": replay.performance.as_dict(),
                }
                runs.append(run)
                write_json(output / f"{year}_{candidate}_{scenario}.json", run)
                print(f"{year}/{candidate}/{scenario}: trades={replay.performance.trades}, "
                      f"net={replay.performance.net_profit}", flush=True)
    assessment = assess(runs)
    result = json_value({
        "protocol_sha256": sha(path), "runs": runs, "assessment": assessment,
        "next_period_note": "2026 price performance remains unevaluated for this selection.",
    })
    if read_protocol(path, datasets)[0] != protocol:
        raise ValueError("Exit protocol changed during evaluation")
    write_json(output / "results.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_json(output / "completion.json", {
        "results_sha256": sha(output / "results.json"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Frozen causal perpetual exit development")
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
        if args.command == "freeze":
            freeze(args.output, args.dataset, args.parent_results)
        else:
            evaluate(args.protocol, args.dataset)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Exit research failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
