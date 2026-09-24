"""Frozen dual-horizon time-series momentum study on seen 2023-2025 data."""

import argparse
import json
import shutil
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.derivatives.observed_costs import ObservedCostScenario, load_observed_cost_scenario
from app.market_data.datasets import write_json
from app.market_data.kraken_futures import load_futures_dataset
from app.strategies.time_series_momentum import TimeSeriesMomentumStrategy
from backtesting.derivative_research import json_value, sha
from backtesting.derivatives import DerivativeBacktester, TrailingStopPolicy


VERSION = "perpetual-dual-horizon-tsmom-development-v1"
FEE_RATE = Decimal("0.0005")
FEE_SOURCE = "Kraken Derivatives published base taker fee, verified 2026-09-23"
TRAILING = TrailingStopPolicy(84, Decimal("4"))
CODE_FILES = (
    "app/domain.py", "app/market_data/models.py", "app/market_data/quality.py",
    "app/market_data/candles.py", "app/market_data/kraken_futures.py",
    "app/market_data/perpetual_cost_calibration.py", "app/indicators/core.py",
    "app/strategies/base.py", "app/strategies/models.py",
    "app/strategies/time_series_momentum.py", "app/derivatives/models.py",
    "app/derivatives/settings.py", "app/derivatives/risk.py",
    "app/derivatives/broker.py", "app/derivatives/observed_costs.py",
    "backtesting/derivatives.py", "backtesting/derivative_research.py",
    "backtesting/derivative_tsmom_research.py",
)


def code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {name: sha(root / name) for name in CODE_FILES}


def cost_cases(observed: ObservedCostScenario) -> dict[str, tuple[object, Decimal]]:
    base = observed.settings
    stress = replace(
        base,
        fee_rate=base.fee_rate * 2,
        spread_bps=base.spread_bps * 2,
        slippage_bps=base.slippage_bps * 2,
    )
    return {
        "observed_p95": (base, observed.funding_rate_per_4h),
        "double_cost_stress": (stress, observed.funding_rate_per_4h * 2),
    }


def definition(observed: ObservedCostScenario) -> dict:
    strategy = TimeSeriesMomentumStrategy()
    cases = {
        name: {
            "settings": json_value(asdict(configured)),
            "adverse_funding_rate_per_4h": str(funding),
        }
        for name, (configured, funding) in cost_cases(observed).items()
    }
    return {
        "market": "PF_XBTUSD", "symbol": "BTC/USD", "timeframe": "4h",
        "development_years": [2023, 2024, 2025],
        "reserved_holdout": "2026-01-01 onward; no 2026 PF_XBTUSD price-performance data loaded",
        "hypothesis": (
            "Agreement between fixed 30-day and 120-day own-price momentum identifies "
            "persistent BTC perpetual trends that survive observed p95 execution costs, "
            "adverse funding, ATR risk scaling and a doubled-cost stress case."
        ),
        "research_basis": [
            "Moskowitz, Ooi and Pedersen (2012), Time Series Momentum.",
            "Han, Kang and Ryu (2026 revision), Momentum in the Cryptocurrency Market under realistic assumptions.",
        ],
        "strategy": {"name": strategy.name, "version": strategy.version,
                     "parameters": json_value(asdict(strategy.parameters))},
        "exit": {"fixed_target": None, "atr_period": 84, "atr_multiple": "4",
                 "anchor": "highest/lowest completed close; active next candle"},
        "cost_source_summary_sha256": observed.source_summary_sha256,
        "fee_source": observed.fee_source,
        "cost_scenarios": list(cases), "cases": cases,
        "gate": {
            "each_year_each_cost": "net_profit > 0, max_drawdown < 10%, liquidations == 0",
            "minimum_trades": 3,
            "maximum_leverage": 10,
            "selection": "candidate only; no fallback and no parameter amendment",
        },
        "rules": [
            "2023-2025 are seen development data and cannot independently prove profitability.",
            "Exactly one parameter set: 180/720-bar momentum, ATR(84), 4-ATR initial and trailing stop.",
            "No volume, breakout, oscillator, machine-learning or funding-timing filters.",
            "Direction requires both return horizons to have the same non-zero sign.",
            "Signals use completed closes and execute no earlier than the next candle open.",
            "Fresh 1000 USD account per year; prior candles may warm indicators but cannot trade.",
            "Sizing risks at most 1% equity and chooses the smallest required leverage up to 10x.",
            "Observed p95 spread/slippage and adverse funding are primary; stress doubles all costs.",
            "A pass must be frozen unchanged before one 2026 evaluation. PAPER and LIVE remain disabled.",
        ],
    }


def load_inputs(datasets: list[Path]):
    trades, marks, manifests = [], [], []
    for dataset in datasets:
        trade, mark, manifest = load_futures_dataset(dataset)
        trades.extend(trade); marks.extend(mark); manifests.append(manifest)
    trade = tuple(sorted(trades, key=lambda candle: candle.timestamp))
    mark = tuple(sorted(marks, key=lambda candle: candle.timestamp))
    stamps = tuple(c.timestamp for c in trade)
    if stamps != tuple(c.timestamp for c in mark) or len(stamps) != len(set(stamps)):
        raise ValueError("Combined trade/mark development data is not uniquely aligned")
    if not trade or trade[0].timestamp.year != 2023 or trade[-1].timestamp.year != 2025:
        raise ValueError("Development inputs must cover 2023 through 2025")
    return trade, mark, manifests


def input_hashes(datasets: list[Path], manifests: list[dict]) -> list[dict]:
    return [{"manifest_sha256": sha(path / "manifest.json"),
             "trade_sha256": manifest["sha256"]["trade.csv"],
             "mark_sha256": manifest["sha256"]["mark.csv"]}
            for path, manifest in zip(datasets, manifests)]


def freeze(output: Path, datasets: list[Path], candidate: Path, summary: Path) -> None:
    if output.exists():
        raise ValueError("Use a new research directory")
    observed = load_observed_cost_scenario(
        candidate, summary, fee_rate=FEE_RATE, fee_source=FEE_SOURCE,
    )
    _, _, manifests = load_inputs(datasets)
    protocol = {
        "protocol_version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "definition": definition(observed),
        "code_sha256": code_hashes(),
        "inputs": input_hashes(datasets, manifests),
        "cost_candidate_sha256": sha(candidate),
        "cost_summary_sha256": sha(summary),
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
        shutil.rmtree(output); raise


def read_protocol(path: Path, datasets: list[Path], candidate: Path, summary: Path):
    observed = load_observed_cost_scenario(
        candidate, summary, fee_rate=FEE_RATE, fee_source=FEE_SOURCE,
    )
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if (protocol.get("protocol_version") != VERSION
            or protocol.get("python_version") != sys.version.split()[0]
            or protocol.get("definition") != definition(observed)
            or protocol.get("code_sha256") != code_hashes()
            or protocol.get("cost_candidate_sha256") != sha(candidate)
            or protocol.get("cost_summary_sha256") != sha(summary)):
        raise ValueError("Frozen TSMOM protocol, source or costs differ")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen source snapshot differs")
    trade, mark, manifests = load_inputs(datasets)
    if input_hashes(datasets, manifests) != protocol["inputs"]:
        raise ValueError("Development inputs differ")
    return protocol, observed, trade, mark


def assess(runs: list[dict]) -> dict:
    indexed = {(run["year"], run["scenario"]): run for run in runs}
    checks = {}
    for year in (2023, 2024, 2025):
        for scenario in ("observed_p95", "double_cost_stress"):
            performance = indexed[year, scenario]["performance"]
            checks[f"{year}/{scenario}"] = {
                "positive_net": Decimal(performance["net_profit"]) > 0,
                "drawdown_below_10_percent": Decimal(performance["max_drawdown"]) < Decimal("0.10"),
                "enough_trades": performance["trades"] >= 3,
                "no_liquidation": performance["liquidations"] == 0,
                "leverage_within_cap": performance["maximum_leverage_used"] <= 10,
            }
    passed = all(all(values.values()) for values in checks.values())
    return {"primary": "dual_horizon_tsmom", "checks": checks,
            "selected": "dual_horizon_tsmom" if passed else None,
            "screen_passed": passed}


def render_report(result: dict) -> str:
    lines = [
        "# Dual-Horizon-Zeitreihen-Momentum", "",
        "2023-2025 sind gesehene Entwicklungsdaten. 2026 wurde nicht ausgewertet.", "",
        "| Jahr | Fall | Trades | Netto USD | Profitfaktor | Max. DD | Funding | Max. Hebel |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in result["runs"]:
        p = run["performance"]; factor = p["profit_factor"] or "–"
        lines.append(
            f"| {run['year']} | {run['scenario']} | {p['trades']} | "
            f"{Decimal(p['net_profit']):.2f} | {factor} | "
            f"{Decimal(p['max_drawdown']) * 100:.2f}% | "
            f"{Decimal(p['funding_paid']):.2f} | {p['maximum_leverage_used']}x |"
        )
    selected = result["assessment"]["selected"] or "keine"
    lines += ["", f"Auswahl: {selected}.",
              "Nur ein vollständiger Gate-Erfolg dürfte unverändert an 2026 geprüft werden.",
              "PAPER und LIVE bleiben gesperrt."]
    return "\n".join(lines) + "\n"


def evaluate(path: Path, datasets: list[Path], candidate: Path, summary: Path) -> None:
    protocol, observed, trade, mark = read_protocol(path, datasets, candidate, summary)
    output = path.parent / "evaluation"; output.mkdir(exist_ok=False)
    strategy = TimeSeriesMomentumStrategy()
    runs = []
    for year in (2023, 2024, 2025):
        year_trade = tuple(c for c in trade if c.timestamp.year == year)
        year_mark = tuple(c for c in mark if c.timestamp.year == year)
        prior = tuple(c for c in trade if c.timestamp < year_trade[0].timestamp)
        warmup = prior[-strategy.parameters.required_history:]
        for scenario, (configured, funding) in cost_cases(observed).items():
            replay = DerivativeBacktester(
                TimeSeriesMomentumStrategy(), configured, funding,
                trailing_stop_policy=TRAILING,
            ).run(year_trade, year_mark, warmup=warmup)
            run = {
                "year": year, "scenario": scenario,
                "warmup_candles": len(warmup), "candles": replay.candles_processed,
                "signals": replay.signals, "entries": replay.entries,
                "rejected_entries": replay.rejected_entries,
                "stop_updates": replay.stop_updates,
                "performance": replay.performance.as_dict(),
            }
            runs.append(run); write_json(output / f"{year}_{scenario}.json", run)
            print(f"{year}/{scenario}: trades={replay.performance.trades}, "
                  f"net={replay.performance.net_profit}", flush=True)
    result = json_value({
        "protocol_sha256": sha(path), "runs": runs, "assessment": assess(runs),
        "next_period_note": "2026 PF_XBTUSD price performance remains unevaluated.",
    })
    if read_protocol(path, datasets, candidate, summary)[0] != protocol:
        raise ValueError("TSMOM protocol changed during evaluation")
    write_json(output / "results.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_json(output / "completion.json", {
        "results_sha256": sha(output / "results.json"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Frozen dual-horizon TSMOM development")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--dataset", type=Path, action="append", required=True)
    prepare.add_argument("--cost-candidate", type=Path, required=True)
    prepare.add_argument("--cost-summary", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dataset", type=Path, action="append", required=True)
    run.add_argument("--cost-candidate", type=Path, required=True)
    run.add_argument("--cost-summary", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            freeze(args.output, args.dataset, args.cost_candidate, args.cost_summary)
        else:
            evaluate(args.protocol, args.dataset, args.cost_candidate, args.cost_summary)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"TSMOM research failed: {exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
