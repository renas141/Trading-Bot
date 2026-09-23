"""Post-holdout diagnostics on now-seen data; never used as holdout evidence."""

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.market_data.datasets import write_json
from app.market_data.kraken_futures import load_futures_dataset
from app.strategies.long_regime import LongOnlyRegimeStrategy
from backtesting.derivative_research import json_value, settings
from backtesting.derivatives import DerivativeBacktester


def diagnose(dataset: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("Use a new diagnostics directory")
    candles, marks, manifest = load_futures_dataset(dataset)
    if manifest["start"] != "2025-01-01T00:00:00+00:00" or manifest["end"] != "2026-01-01T00:00:00+00:00":
        raise ValueError("This diagnostic is explicitly scoped to the now-seen 2025 holdout")
    output.mkdir(parents=True)
    cases = []
    for scenario in ("current_conservative", "stress"):
        configured, funding = settings(scenario, 10)
        replay = DerivativeBacktester(LongOnlyRegimeStrategy(), configured, funding).run(candles, marks)
        trades = []
        for trade in replay.trades:
            covered = [c for c in candles
                       if trade.position.opened_at <= c.timestamp and c.timestamp <= trade.closed_at]
            fully_observed = [c for c in covered if c.closed_at <= trade.closed_at]
            risk_distance = trade.position.entry_price - trade.position.stop_price
            # The order of prices inside the exit candle is unknown. Excluding
            # its high/low avoids claiming excursions that may have happened
            # only after the simulated exit.
            maximum = max([trade.position.entry_price, trade.exit_price]
                          + [c.high for c in fully_observed])
            minimum = min([trade.position.entry_price, trade.exit_price]
                          + [c.low for c in fully_observed])
            trades.append(json_value({
                "opened_at": trade.position.opened_at.isoformat(),
                "closed_at": trade.closed_at.isoformat(),
                "bars_held": len(covered),
                "exit_reason": trade.exit_reason,
                "entry_price": trade.position.entry_price,
                "stop_price": trade.position.stop_price,
                "target_price": trade.position.take_profit_price,
                "leverage": trade.position.leverage,
                "quantity": trade.position.quantity,
                "maximum_favorable_r": (maximum - trade.position.entry_price) / risk_distance,
                "maximum_adverse_r": (trade.position.entry_price - minimum) / risk_distance,
                "price_pnl": trade.price_pnl,
                "fees": trade.fees,
                "funding_paid": trade.funding_paid,
                "net_pnl": trade.net_pnl,
            }))
        cases.append({"scenario": scenario, "performance": replay.performance.as_dict(), "trades": trades})
    result = {"scope": "post-holdout diagnostic; 2025 is seen development data",
              "created_at": datetime.now().astimezone().isoformat(), "cases": cases}
    write_json(output / "diagnostics.json", result)
    lines = ["# Diagnose der fünf 2025-Perpetual-Trades", "",
             "Diese Analyse entstand nach dem fehlgeschlagenen Holdout. 2025 ist gesehen und darf für folgende Änderungen nur als Entwicklungsdatenbasis dienen.", "",
             "| Fall | Einstieg | Bars | Ende | MFE in R | MAE in R | Funding | Netto USD | Grund |",
             "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |"]
    for case in cases:
        for trade in case["trades"]:
            lines.append(f"| {case['scenario']} | {trade['opened_at'][:10]} | {trade['bars_held']} | {trade['closed_at'][:10]} | {Decimal(trade['maximum_favorable_r']):.2f} | {Decimal(trade['maximum_adverse_r']):.2f} | {Decimal(trade['funding_paid']):.2f} | {Decimal(trade['net_pnl']):.2f} | {trade['exit_reason']} |")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Diagnose the failed 2025 perpetual holdout")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        diagnose(args.dataset, args.output)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Derivative diagnostics failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
