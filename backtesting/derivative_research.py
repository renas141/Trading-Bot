"""Preregistered 2023/2024 development study for the first perpetual hypothesis."""

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.derivatives.settings import DerivativeSettings
from app.market_data.datasets import write_json
from app.market_data.kraken_futures import load_futures_dataset
from app.strategies.regime_breakout import RegimeBreakoutStrategy
from backtesting.derivatives import DerivativeBacktester

VERSION = "perpetual-regime-development-v1"
CODE_FILES = (
    "app/domain.py",
    "app/market_data/models.py",
    "app/market_data/quality.py",
    "app/market_data/candles.py",
    "app/market_data/kraken_futures.py",
    "app/indicators/core.py",
    "app/strategies/base.py",
    "app/strategies/models.py",
    "app/strategies/regime_breakout.py",
    "app/derivatives/models.py",
    "app/derivatives/settings.py",
    "app/derivatives/risk.py",
    "app/derivatives/broker.py",
    "backtesting/derivatives.py",
    "backtesting/derivative_research.py",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {name: sha(root / name) for name in CODE_FILES}


def settings(scenario: str, leverage: int) -> tuple[DerivativeSettings, Decimal]:
    if scenario == "current_conservative":
        fee, slippage, funding = Decimal("0.0005"), Decimal("5"), Decimal("0.00005")
    elif scenario == "stress":
        fee, slippage, funding = Decimal("0.001"), Decimal("10"), Decimal("0.0002")
    else:
        raise ValueError("Unknown cost scenario")
    base = DerivativeSettings(fee_rate=fee, slippage_bps=slippage)
    if leverage == 1:
        return replace(base, max_leverage=1, max_margin_fraction=Decimal("1")), funding
    if leverage == 10:
        return replace(base, max_leverage=10, max_margin_fraction=Decimal("0.10")), funding
    raise ValueError("Unknown leverage variant")


def definition() -> dict:
    strategy = RegimeBreakoutStrategy()
    cases = {}
    for scenario in ("current_conservative", "stress"):
        for name, leverage in (("regime_1x", 1), ("regime_dynamic_10x", 10)):
            configured, funding = settings(scenario, leverage)
            cases[f"{name}/{scenario}"] = {
                "settings": json_value(asdict(configured)),
                "funding_rate_per_4h": str(funding),
            }
    return {
        "market": "PF_XBTUSD",
        "symbol": "BTC/USD",
        "timeframe": "4h",
        "development_years": [2023, 2024],
        "reserved_holdout_year": 2025,
        "hypothesis": (
            "A symmetric slow breakout restricted to persistent higher-timeframe trends, "
            "moderate volatility and current volume can remain positive after perpetual costs."
        ),
        "strategy": {"name": strategy.name, "version": strategy.version,
                     "parameters": json_value(asdict(strategy.parameters))},
        "variants": ["regime_1x", "regime_dynamic_10x"],
        "cost_scenarios": ["current_conservative", "stress"],
        "cases": cases,
        "primary": "regime_dynamic_10x",
        "gate": {
            "each_year_each_cost": "net_profit > 0, max_drawdown < 10%, liquidations == 0",
            "minimum_trades": {"current_conservative": 5, "stress": 3},
            "leverage": "maximum observed leverage <= 10 and smallest required leverage chosen",
            "comparison": "dynamic variant must not underperform the 1x variant in any matched case",
        },
        "rules": [
            "2023/2024 are development data and do not prove future profitability.",
            "Exactly one fixed strategy parameter set; no sweep or post-result edits in this protocol.",
            "Signals use only completed trade candles and execute at the next trade-candle open.",
            "Stops/targets use trade prices; liquidation uses the separate mark-price series.",
            "Risk is capped at 1% of equity per trade; 10x is an absolute cap, never a target.",
            "The dynamic variant chooses the smallest leverage that fits a 10% collateral allocation.",
            "Current fee uses 0.05% taker per side and 5 bps slippage; stress doubles both.",
            "Historical public funding is unavailable for these years. Fixed adverse funding sensitivity is charged to both directions, never assumed zero.",
            "Normal adverse funding is 0.005% per 4h; stress is 0.02% per 4h while a position is open.",
            "If stop and target are touched in one bar, stop wins. Gap stops receive the worse open.",
            "Fresh 1000 USD account and fresh in-year warm-up per year/case; no compounding across years.",
            "2025 stays unopened unless this exact primary gate passes; LIVE trading remains disabled.",
        ],
    }


def freeze(output: Path, dataset: Path) -> Path:
    if output.exists():
        raise ValueError("Use a new research directory")
    _, _, manifest = load_futures_dataset(dataset)
    protocol = {
        "protocol_version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "definition": definition(),
        "code_sha256": code_hashes(),
        "input_manifest_sha256": sha(dataset / "manifest.json"),
        "input_trade_sha256": manifest["sha256"]["trade.csv"],
        "input_mark_sha256": manifest["sha256"]["mark.csv"],
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
    return output / "protocol.json"


def read_protocol(path: Path, dataset: Path) -> tuple[dict, tuple, tuple]:
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if (protocol.get("protocol_version") != VERSION or protocol.get("python_version") != sys.version.split()[0]
            or protocol.get("definition") != definition() or protocol.get("code_sha256") != code_hashes()
            or protocol.get("input_manifest_sha256") != sha(dataset / "manifest.json")):
        raise ValueError("Frozen protocol, runtime, source or dataset differs")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen source snapshot differs")
    trade, mark, manifest = load_futures_dataset(dataset)
    if (protocol["input_trade_sha256"] != manifest["sha256"]["trade.csv"]
            or protocol["input_mark_sha256"] != manifest["sha256"]["mark.csv"]):
        raise ValueError("Input candle checksums differ")
    return protocol, trade, mark


def assess(runs: list[dict]) -> dict:
    indexed = {(run["year"], run["variant"], run["scenario"]): run for run in runs}
    checks = {}
    for year in (2023, 2024):
        for scenario, minimum in (("current_conservative", 5), ("stress", 3)):
            primary = indexed[year, "regime_dynamic_10x", scenario]["performance"]
            control = indexed[year, "regime_1x", scenario]["performance"]
            checks[f"{year}/{scenario}"] = {
                "positive_net": Decimal(primary["net_profit"]) > 0,
                "drawdown_below_10_percent": Decimal(primary["max_drawdown"]) < Decimal("0.10"),
                "enough_trades": primary["trades"] >= minimum,
                "no_liquidation": primary["liquidations"] == 0,
                "leverage_within_cap": primary["maximum_leverage_used"] <= 10,
                "not_worse_than_1x": Decimal(primary["net_profit"]) >= Decimal(control["net_profit"]),
            }
    return {"checks": checks, "screen_passed": all(all(values.values()) for values in checks.values())}


def render_report(result: dict) -> str:
    lines = [
        "# Perpetual-Regime-Hypothese: Entwicklungsprüfung",
        "",
        "2023/2024 sind Entwicklungsdaten. Die Ergebnisse sind keine Garantie und keine unabhängige Bestätigung.",
        "",
        "| Jahr | Variante | Kosten/Funding | Trades | Netto USD | Max. DD | Gebühren | Funding | Liquidationen | Max. Hebel |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in result["runs"]:
        p = run["performance"]
        lines.append(
            f"| {run['year']} | {run['variant']} | {run['scenario']} | {p['trades']} | "
            f"{Decimal(p['net_profit']):.2f} | {Decimal(p['max_drawdown'])*100:.2f}% | "
            f"{Decimal(p['fees']):.2f} | {Decimal(p['funding_paid']):.2f} | "
            f"{p['liquidations']} | {p['maximum_leverage_used']}x |"
        )
    lines += ["", f"Gate bestanden: {'ja' if result['assessment']['screen_passed'] else 'nein'}.",
              result["holdout_note"], "",
              "Funding ist eine festgelegte nachteilige Sensitivität, weil die öffentliche Kraken-Historie für 2023/2024 keine vollständigen Funding-Sätze liefert.",
              "Der Hebel ändert bei gleicher risikobasierter Positionsgröße vor allem die gebundene Margin; er erzeugt keinen statistischen Vorteil.",
              "LIVE bleibt gesperrt."]
    return "\n".join(lines) + "\n"


def evaluate(protocol_path: Path, dataset: Path) -> dict:
    protocol, trade, mark = read_protocol(protocol_path, dataset)
    output = protocol_path.parent / "evaluation"
    output.mkdir(exist_ok=False)
    runs = []
    for year in protocol["definition"]["development_years"]:
        year_trade = tuple(c for c in trade if c.timestamp.year == year)
        year_mark = tuple(c for c in mark if c.timestamp.year == year)
        for variant, leverage in (("regime_1x", 1), ("regime_dynamic_10x", 10)):
            for scenario in protocol["definition"]["cost_scenarios"]:
                configured, funding = settings(scenario, leverage)
                replay = DerivativeBacktester(RegimeBreakoutStrategy(), configured, funding).run(year_trade, year_mark)
                run = {
                    "year": year,
                    "variant": variant,
                    "scenario": scenario,
                    "candles": replay.candles_processed,
                    "signals": replay.signals,
                    "entries": replay.entries,
                    "rejected_entries": replay.rejected_entries,
                    "performance": replay.performance.as_dict(),
                }
                runs.append(run)
                write_json(output / f"{year}_{variant}_{scenario}.json", run)
                print(f"{year}/{variant}/{scenario}: trades={replay.performance.trades}, net={replay.performance.net_profit}", flush=True)
    assessment = assess(runs)
    note = ("Das Entwicklungstor ist bestanden; eine separate einmalige 2025-Prüfung darf vorbereitet werden."
            if assessment["screen_passed"] else
            "Das Entwicklungstor ist nicht bestanden. 2025 bleibt für diese Hypothese ungeöffnet.")
    result = json_value({
        "protocol_sha256": sha(protocol_path),
        "input_manifest_sha256": sha(dataset / "manifest.json"),
        "runs": runs,
        "assessment": assessment,
        "holdout_note": note,
    })
    if read_protocol(protocol_path, dataset)[0] != protocol:
        raise ValueError("Protocol or source changed during evaluation")
    write_json(output / "results.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_json(output / "completion.json", {
        "results_sha256": sha(output / "results.json"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Frozen perpetual regime development research")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--dataset", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            print(freeze(args.output, args.dataset))
        else:
            evaluate(args.protocol, args.dataset)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Derivative research failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
