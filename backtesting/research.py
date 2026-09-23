"""Fixed-parameter development/holdout evaluation with predefined cost stress."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.config.settings import Settings
from app.database.repository import Repository
from app.domain import TradingMode
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import PaperBroker
from app.market_data.cli import timestamp
from app.market_data.datasets import load_dataset, write_json
from app.risk.stop_risk import StopRiskManager
from app.strategies.registry import make_strategy, strategy_metadata
from app.strategies.trend_breakout import TrendBreakoutParameters
from backtesting.engine import Backtester
from backtesting.execution import BacktestExecution


def research(dataset: Path, split_at: datetime, output: Path) -> dict[str, object]:
    """One frozen hypothesis, no parameter search or automatic winner selection."""
    candles, manifest = load_dataset(dataset)
    if (manifest["symbol"], manifest["timeframe"]) != ("BTC/EUR", "15m"):
        raise ValueError("This research protocol requires BTC/EUR 15m data")
    if split_at.tzinfo is None or split_at.utcoffset() is None:
        raise ValueError("Split requires a timezone")
    development = tuple(c for c in candles if c.closed_at <= split_at)
    holdout = tuple(c for c in candles if c.timestamp >= split_at)
    warmup_count = TrendBreakoutParameters().required_history - 1
    if (len(development) <= warmup_count or len(holdout) < 2
            or len(development) + len(holdout) != len(candles)
            or development[-1].closed_at != split_at or holdout[0].timestamp != split_at):
        raise ValueError("Split requires sufficient contiguous development and holdout data")
    base = Settings(mode=TradingMode.BACKTEST, paper_spread_bps=Decimal("10"))
    scenarios = {"base": base, "double_costs": replace(base, paper_fee_rate=base.paper_fee_rate * 2,
                 paper_slippage_bps=base.paper_slippage_bps * 2, paper_spread_bps=base.paper_spread_bps * 2)}
    protocol = {
        "protocol_version": "fixed-hypothesis-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy_metadata("trend_breakout"), "market": "BTC/EUR", "timeframe": "15m",
        "input_sha256": manifest["sha256"]["candles.csv"],
        "python_version": sys.version.split()[0],
        "code_sha256": {
            str(path.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(path.read_bytes()).hexdigest()
            for package in ("app", "backtesting")
            for path in sorted((Path(__file__).resolve().parents[1] / package).rglob("*.py"))
        },
        "split_at": split_at.astimezone(timezone.utc).isoformat(),
        "development_rows": len(development), "holdout_rows": len(holdout),
        "holdout_warmup_rows": warmup_count,
        "initial_capital_each_run": str(base.initial_capital),
        "costs": {name: {"fee_rate": str(s.paper_fee_rate), "slippage_bps": str(s.paper_slippage_bps),
                         "spread_bps": str(s.paper_spread_bps)} for name, s in scenarios.items()},
        "rules": ["Parameters fixed before any performance calculation; no optimizer.",
                  "Fresh account and strategy per run; no positions transferred across the split.",
                  "Holdout warm-up uses only preceding development candles, without execution.",
                  "Both cost scenarios are reported; no selection based on holdout performance.",
                  "Observed holdout becomes evaluation data; changes require a new untouched period."],
    }
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "protocol.json", protocol)
    protocol_hash = hashlib.sha256((output / "protocol.json").read_bytes()).hexdigest()
    results = []
    with Repository(output / "research.sqlite3") as repository:
        for period, selected, warmup in (("development", development, ()),
                                         ("holdout", holdout, development[-warmup_count:])):
            for name, settings in scenarios.items():
                session = repository.start_session(settings.mode, settings.initial_capital, settings.symbol)
                try:
                    broker = PaperBroker(settings, repository, session)
                    manager = OrderManager(StopRiskManager(settings), broker, repository, session)
                    execution = BacktestExecution(manager, broker, repository, session)
                    result = Backtester(make_strategy("trend_breakout"), execution).run(selected, warmup=warmup)
                    assumptions = {"protocol_sha256": protocol_hash, "period": period, "cost_scenario": name,
                                   "strategy": protocol["strategy"], "risk": settings.risk,
                                   "execution_model": "cash-long-next-bar-v1", "costs": protocol["costs"][name],
                                   "price_tick": settings.price_tick, "quantity_step": settings.quantity_step,
                                   "min_order_notional": settings.min_order_notional,
                                   "input_sha256": protocol["input_sha256"]}
                    repository.record_backtest_result(session, result, assumptions)
                    signals = repository.records("signals", session)
                    rejected = Counter()
                    long_signals = approved = 0
                    for row in signals:
                        signal, decision = json.loads(row["payload"]), json.loads(row["risk_decision"])
                        if signal["direction"] == "LONG":
                            long_signals += 1
                            approved += int(decision["allowed"])
                            if not decision["allowed"]:
                                rejected[decision["reasons"][0]] += 1
                    results.append({"period": period, "cost_scenario": name, "session_id": session,
                                    "start": selected[0].timestamp.isoformat(), "end": selected[-1].closed_at.isoformat(),
                                    "long_signals": long_signals, "approved_entries": approved,
                                    "rejected_entry_reasons": dict(rejected), "performance": result.performance.as_dict()})
                    repository.finish_session(session)
                    print(f"Completed {period}/{name}: trades={result.performance.trades}, net={result.performance.net_profit}", flush=True)
                except BaseException:
                    repository.finish_session(session, failed=True)
                    raise
    report = {"protocol_sha256": protocol_hash, "runs": results,
              "note": "Descriptive research only. No automatic strategy activation or profitability claim."}
    write_json(output / "results.json", report)
    lines = ["# Forschungsbericht: trend_breakout 0.1.0", "",
             "Feste, nicht optimierte Hypothese; vollständig finanzierte LONG-Simulation. Kapital je Lauf: 1.000 EUR.",
             "", "| Zeitraum | Kosten | Trades | Netto EUR | Rendite % | Max. Drawdown % | Gebühren EUR |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for run in results:
        p = run["performance"]
        lines.append(f"| {run['period']} | {run['cost_scenario']} | {p['trades']} | {Decimal(p['net_profit']):.2f} | "
                     f"{Decimal(p['return_fraction']) * 100:.2f} | {Decimal(p['max_drawdown']) * 100:.2f} | {Decimal(p['fees']):.2f} |")
    lines += ["", "Die Holdout-Daten wurden nicht zur Parameteranpassung verwendet. Nach dieser Auswertung gelten sie als gesehen.",
              "Die Stressvariante verdoppelt Gebühren, Slippage und Spread. Keine Variante wird automatisch ausgewählt.",
              "Keine Tick-Rekonstruktion, keine SHORTs, kein Hebel. Drawdown bezieht sich auf beobachtete Simulationsereignisse.",
              "", "Ein- und Ausstiege, Gründe, Risikoablehnungen und Equity sind in research.sqlite3 dokumentiert.",
              "Parameter und Datenprüfsumme stehen in protocol.json; vollständige Kennzahlen in results.json."]
    with (output / "report.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed trend-breakout development/holdout research")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split-at", type=timestamp, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        research(args.dataset, args.split_at, args.output)
        return 0
    except (ValueError, OSError) as exc:
        print(f"Research failed ({type(exc).__name__}); inspect data, split and output path.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
