"""Frozen regime-confirmed momentum study on seen 2023-2025 data."""

import argparse
import json
import shutil
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.derivatives.observed_costs import ObservedCostScenario, load_observed_cost_scenario
from app.derivatives.settings import DerivativeSettings
from app.market_data.datasets import write_json
from app.market_data.kraken_futures import load_futures_dataset
from app.market_data.kraken_perpetual_regime_history import load_dataset as load_regime_dataset
from app.market_data.perpetual_regime_alignment import align_futures_regime
from app.strategies.regime_confirmed_momentum import (
    RegimeConfirmedMomentumParameters,
    RegimeConfirmedMomentumStrategy,
)
from backtesting.derivative_research import json_value, sha
from backtesting.derivatives import CloseExitPolicy, DerivativeBacktester


VERSION = "perpetual-regime-confirmed-momentum-development-v1"
FEE_RATE = Decimal("0.0005")
FEE_SOURCE = "Kraken Derivatives published base taker fee, verified 2026-09-23"
EXIT = CloseExitPolicy(max_holding_bars=42)
CODE_FILES = (
    "app/domain.py", "app/market_data/models.py", "app/market_data/quality.py",
    "app/market_data/candles.py", "app/market_data/kraken_futures.py",
    "app/market_data/kraken_perpetual_regime.py",
    "app/market_data/kraken_perpetual_regime_history.py",
    "app/market_data/perpetual_regime_alignment.py", "app/indicators/core.py",
    "app/strategies/base.py", "app/strategies/models.py",
    "app/strategies/regime_confirmed_momentum.py", "app/derivatives/models.py",
    "app/derivatives/settings.py", "app/derivatives/risk.py",
    "app/derivatives/broker.py", "app/derivatives/observed_costs.py",
    "backtesting/derivatives.py", "backtesting/derivative_research.py",
    "backtesting/derivative_regime_momentum_research.py",
)


def code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {name: sha(root / name) for name in CODE_FILES}


def cost_cases(observed: ObservedCostScenario) -> dict[str, tuple[DerivativeSettings, Decimal]]:
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
    parameters = RegimeConfirmedMomentumParameters()
    cases = {
        name: {"settings": json_value(asdict(settings)),
               "adverse_funding_rate_per_4h": str(funding)}
        for name, (settings, funding) in cost_cases(observed).items()
    }
    return {
        "market": "PF_XBTUSD", "symbol": "BTC/USD", "timeframe": "4h",
        "development_years": [2023, 2024, 2025],
        "reserved_outcome_holdout": (
            "2026 PF_XBTUSD price outcomes remain unloaded; 2026 feature distributions were "
            "inspected, so a fully blind regime period begins after 2026-09-24"
        ),
        "hypothesis": (
            "A fixed 7/28-day price trend is more robust when seven-day open interest rises "
            "and both the delayed current aggressor differential and seven-day CVD change "
            "agree with the trend direction."
        ),
        "exploration_disclosure": (
            "Eight confirmation combinations were descriptively compared on seen 2023-2025 "
            "development outcomes before this replay rule was fixed. The replay is therefore "
            "development evidence and cannot validate the hypothesis independently."
        ),
        "strategy": {
            "name": RegimeConfirmedMomentumStrategy.name,
            "version": RegimeConfirmedMomentumStrategy.version,
            "parameters": json_value(asdict(parameters)),
            "entry_checks": [
                "7-day and 28-day close returns have the same non-zero sign",
                "7-day open-interest change is positive",
                "latest delayed aggressor differential agrees with direction",
                "7-day delayed CVD change agrees with direction",
            ],
            "excluded_filters": [
                "long-short ratio", "rolling-volatility threshold",
                "liquidation-volume threshold", "parameter search",
            ],
        },
        "timing": {
            "analytics_bucket": "treated as complete at timestamp + 4h",
            "safety_lag": "one additional 4h price candle before signal evaluation",
            "execution": "next candle open after the close-confirmed signal",
        },
        "exit": {"maximum_holding_bars": 42, "fixed_target": None,
                 "protective_stop": "ATR(42) x 3"},
        "cost_source_summary_sha256": observed.source_summary_sha256,
        "fee_source": observed.fee_source,
        "cost_scenarios": list(cases), "cases": cases,
        "gate": {
            "each_year_each_cost": "net_profit > 0, max_drawdown < 10%, liquidations == 0",
            "minimum_trades_per_year": 6,
            "maximum_leverage": 10,
            "selection": "research candidate only; no fallback, activation or amendment",
        },
        "rules": [
            "2023-2025 are seen development data and cannot independently prove profitability.",
            "The 2023 common regime history begins 2023-05-31; no values are imputed.",
            "Fresh 1000 USD account per year; earlier aligned bars may only warm indicators.",
            "Sizing risks at most 1% equity and chooses the smallest required leverage up to 10x.",
            "Observed p95 spread/slippage and adverse funding are primary; stress doubles all costs.",
            "Any rule change after results is a new hypothesis and cannot rescue this gate.",
            "PAPER and LIVE remain disabled regardless of the development result.",
        ],
    }


def load_inputs(price_datasets: list[Path], regime_datasets: list[Path]):
    trade_by_time, mark_by_time, price_manifests = {}, {}, []
    for path in price_datasets:
        trade, mark, manifest = load_futures_dataset(path)
        price_manifests.append(manifest)
        for trade_candle, mark_candle in zip(trade, mark):
            if (trade_candle.timestamp in trade_by_time
                    and (trade_by_time[trade_candle.timestamp] != trade_candle
                         or mark_by_time[trade_candle.timestamp] != mark_candle)):
                raise ValueError("Conflicting duplicate price candle")
            trade_by_time[trade_candle.timestamp] = trade_candle
            mark_by_time[mark_candle.timestamp] = mark_candle
    timestamps = sorted(trade_by_time)
    trade = tuple(trade_by_time[stamp] for stamp in timestamps)
    mark = tuple(mark_by_time[stamp] for stamp in timestamps)

    regime_rows, regime_manifests = [], []
    for path in regime_datasets:
        rows, manifest = load_regime_dataset(path)
        regime_rows.extend(rows)
        regime_manifests.append(manifest)
    regime_rows.sort(key=lambda row: row["timestamp"])
    if len({row["timestamp"] for row in regime_rows}) != len(regime_rows):
        raise ValueError("Regime datasets overlap")
    aligned = align_futures_regime(trade, mark, tuple(regime_rows))
    if ({bar.trade.timestamp.year for bar in aligned} != {2023, 2024, 2025}
            or aligned[0].trade.timestamp.isoformat() != "2023-05-31T16:00:00+00:00"):
        raise ValueError("Aligned development inputs have unexpected coverage")
    return aligned, price_manifests, regime_manifests


def input_hashes(paths: list[Path], manifests: list[dict], *, regime: bool) -> list[dict]:
    rows = []
    for path, manifest in zip(paths, manifests):
        values = {"manifest_sha256": sha(path / "manifest.json")}
        if regime:
            values["regime_sha256"] = manifest["sha256"]["regime.csv"]
        else:
            values["trade_sha256"] = manifest["sha256"]["trade.csv"]
            values["mark_sha256"] = manifest["sha256"]["mark.csv"]
        rows.append(values)
    return rows


def freeze(output: Path, prices: list[Path], regimes: list[Path],
           candidate: Path, summary: Path) -> None:
    if output.exists():
        raise ValueError("Use a new research directory")
    observed = load_observed_cost_scenario(candidate, summary, fee_rate=FEE_RATE,
                                           fee_source=FEE_SOURCE)
    _, price_manifests, regime_manifests = load_inputs(prices, regimes)
    protocol = {
        "protocol_version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "definition": definition(observed),
        "code_sha256": code_hashes(),
        "price_inputs": input_hashes(prices, price_manifests, regime=False),
        "regime_inputs": input_hashes(regimes, regime_manifests, regime=True),
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
        shutil.rmtree(output)
        raise


def read_protocol(path: Path, prices: list[Path], regimes: list[Path],
                  candidate: Path, summary: Path):
    observed = load_observed_cost_scenario(candidate, summary, fee_rate=FEE_RATE,
                                           fee_source=FEE_SOURCE)
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if (protocol.get("protocol_version") != VERSION
            or protocol.get("python_version") != sys.version.split()[0]
            or protocol.get("definition") != definition(observed)
            or protocol.get("code_sha256") != code_hashes()
            or protocol.get("cost_candidate_sha256") != sha(candidate)
            or protocol.get("cost_summary_sha256") != sha(summary)):
        raise ValueError("Frozen regime protocol, source or costs differ")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen source snapshot differs")
    aligned, price_manifests, regime_manifests = load_inputs(prices, regimes)
    if (input_hashes(prices, price_manifests, regime=False) != protocol["price_inputs"]
            or input_hashes(regimes, regime_manifests, regime=True) != protocol["regime_inputs"]):
        raise ValueError("Development inputs differ")
    return protocol, observed, aligned


def assess(runs: list[dict]) -> dict:
    indexed = {(run["year"], run["scenario"]): run for run in runs}
    checks = {}
    for year in (2023, 2024, 2025):
        for scenario in ("observed_p95", "double_cost_stress"):
            performance = indexed[year, scenario]["performance"]
            checks[f"{year}/{scenario}"] = {
                "positive_net": Decimal(performance["net_profit"]) > 0,
                "drawdown_below_10_percent": Decimal(performance["max_drawdown"]) < Decimal("0.10"),
                "enough_trades": performance["trades"] >= 6,
                "no_liquidation": performance["liquidations"] == 0,
                "leverage_within_cap": performance["maximum_leverage_used"] <= 10,
            }
    passed = all(all(values.values()) for values in checks.values())
    return {"primary": "regime_confirmed_momentum", "checks": checks,
            "selected": "regime_confirmed_momentum" if passed else None,
            "screen_passed": passed}


def render_report(result: dict) -> str:
    lines = [
        "# Regimebestätigtes Momentum", "",
        "2023-2025 sind gesehene Entwicklungsdaten; acht Bestätigungskombinationen wurden zuvor exploriert.",
        "2026-Kursresultate wurden nicht ausgewertet.", "",
        "| Jahr | Fall | Trades | Netto USD | Profitfaktor | Max. DD | Funding | Max. Hebel |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in result["runs"]:
        p = run["performance"]
        lines.append(
            f"| {run['year']} | {run['scenario']} | {p['trades']} | "
            f"{Decimal(p['net_profit']):.2f} | {p['profit_factor'] or '–'} | "
            f"{Decimal(p['max_drawdown']) * 100:.2f}% | "
            f"{Decimal(p['funding_paid']):.2f} | {p['maximum_leverage_used']}x |"
        )
    selected = result["assessment"]["selected"] or "keine"
    lines += ["", f"Entwicklungs-Gate: {selected}.",
              "Ein Erfolg wäre nur ein Kandidat für spätere unabhängige Beobachtung.",
              "PAPER und LIVE bleiben gesperrt."]
    return "\n".join(lines) + "\n"


def evaluate(path: Path, prices: list[Path], regimes: list[Path],
             candidate: Path, summary: Path) -> None:
    protocol, observed, aligned = read_protocol(path, prices, regimes, candidate, summary)
    output = path.parent / "evaluation"
    output.mkdir(exist_ok=False)
    runs = []
    for year in (2023, 2024, 2025):
        year_bars = tuple(bar for bar in aligned if bar.trade.timestamp.year == year)
        prior = tuple(bar.trade for bar in aligned if bar.trade.timestamp < year_bars[0].trade.timestamp)
        warmup = prior[-RegimeConfirmedMomentumParameters().required_history:]
        for scenario, (settings, funding) in cost_cases(observed).items():
            replay = DerivativeBacktester(
                RegimeConfirmedMomentumStrategy(aligned), settings, funding,
                close_exit_policy=EXIT,
            ).run(tuple(bar.trade for bar in year_bars),
                  tuple(bar.mark for bar in year_bars), warmup=warmup)
            run = {
                "year": year, "scenario": scenario,
                "warmup_candles": len(warmup), "candles": replay.candles_processed,
                "signals": replay.signals, "entries": replay.entries,
                "rejected_entries": replay.rejected_entries,
                "performance": replay.performance.as_dict(),
            }
            runs.append(run)
            write_json(output / f"{year}_{scenario}.json", run)
            print(f"{year}/{scenario}: trades={replay.performance.trades}, "
                  f"net={replay.performance.net_profit}", flush=True)
    result = json_value({
        "protocol_sha256": sha(path), "runs": runs, "assessment": assess(runs),
        "holdout_note": (
            "2026 PF_XBTUSD price outcomes remain unloaded. Feature distributions were seen; "
            "the fully blind regime period begins after 2026-09-24."
        ),
    })
    if read_protocol(path, prices, regimes, candidate, summary)[0] != protocol:
        raise ValueError("Regime protocol changed during evaluation")
    write_json(output / "results.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_json(output / "completion.json", {
        "results_sha256": sha(output / "results.json"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Frozen regime-confirmed momentum development")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--price-dataset", type=Path, action="append", required=True)
    prepare.add_argument("--regime-dataset", type=Path, action="append", required=True)
    prepare.add_argument("--cost-candidate", type=Path, required=True)
    prepare.add_argument("--cost-summary", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--price-dataset", type=Path, action="append", required=True)
    run.add_argument("--regime-dataset", type=Path, action="append", required=True)
    run.add_argument("--cost-candidate", type=Path, required=True)
    run.add_argument("--cost-summary", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            freeze(args.output, args.price_dataset, args.regime_dataset,
                   args.cost_candidate, args.cost_summary)
        else:
            evaluate(args.protocol, args.price_dataset, args.regime_dataset,
                     args.cost_candidate, args.cost_summary)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Regime-momentum research failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
