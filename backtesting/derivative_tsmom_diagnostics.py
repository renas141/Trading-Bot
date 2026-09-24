"""Post-screen diagnostics for the failed dual-horizon TSMOM study."""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.domain import Direction
from app.market_data.datasets import write_json
from app.strategies.time_series_momentum import TimeSeriesMomentumStrategy
from backtesting.derivative_research import json_value, sha
from backtesting.derivative_tsmom_research import TRAILING, cost_cases, read_protocol
from backtesting.derivatives import DerivativeBacktester


def summarize(trades) -> dict:
    rows = list(trades)
    pnl = [trade.net_pnl for trade in rows]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = -sum(losses, Decimal("0"))
    return json_value({
        "trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "net_profit": sum(pnl, Decimal("0")),
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "fees": sum((trade.fees for trade in rows), Decimal("0")),
        "funding_paid": sum((trade.funding_paid for trade in rows), Decimal("0")),
    })


def diagnose(protocol_path: Path, datasets: list[Path], candidate: Path,
             summary: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("Use a new diagnostics directory")
    protocol, observed, trade, mark = read_protocol(
        protocol_path, datasets, candidate, summary,
    )
    result = {
        "scope": "post-screen diagnostic; 2023-2025 are seen development data",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": sha(protocol_path),
        "evaluation_results_sha256": sha(protocol_path.parent / "evaluation" / "results.json"),
        "warning": (
            "Direction attribution describes trades from the original strategy. "
            "It is not a counterfactual LONG-only or SHORT-only replay."
        ),
        "runs": [],
    }
    strategy = TimeSeriesMomentumStrategy()
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
            by_direction = {
                direction.value: summarize(
                    item for item in replay.trades if item.position.direction == direction
                )
                for direction in (Direction.LONG, Direction.SHORT)
            }
            reasons = defaultdict(list)
            for item in replay.trades:
                reasons[item.exit_reason].append(item)
            result["runs"].append({
                "year": year,
                "scenario": scenario,
                "all": summarize(replay.trades),
                "by_direction": by_direction,
                "by_exit_reason": {
                    name: summarize(items) for name, items in sorted(reasons.items())
                },
            })
    if read_protocol(protocol_path, datasets, candidate, summary)[0] != protocol:
        raise ValueError("Frozen TSMOM protocol changed during diagnostics")
    output.mkdir(parents=True)
    write_json(output / "diagnostics.json", result)
    lines = [
        "# Diagnose des dualen Zeitreihen-Momentums", "",
        "Diese Zerlegung entstand nach dem fehlgeschlagenen Entwicklungstor. Alle Jahre sind gesehen.",
        "Die Richtungswerte ordnen nur die tatsächlich entstandenen Trades zu; sie simulieren keine neue LONG-only- oder SHORT-only-Regel.", "",
        "| Jahr | Kostenfall | Richtung | Trades | Gewinner | Netto USD | Profitfaktor | Gebühren | Funding |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in result["runs"]:
        for direction in ("LONG", "SHORT"):
            values = run["by_direction"][direction]
            factor = Decimal(values["profit_factor"]).__format__(".3f") if values["profit_factor"] else "–"
            lines.append(
                f"| {run['year']} | {run['scenario']} | {direction} | {values['trades']} | "
                f"{values['wins']} | {Decimal(values['net_profit']):.2f} | {factor} | "
                f"{Decimal(values['fees']):.2f} | {Decimal(values['funding_paid']):.2f} |"
            )
    lines += [
        "", "## Befund", "",
        "2024 kam der Gewinn vollständig aus LONG-Trades; SHORT verlor. 2025 waren jedoch auch die LONG-Trades schon vor einer möglichen Richtungsbeschränkung negativ. Das Entfernen der SHORT-Seite allein löst den Fehlschlag daher nicht. Eine nachträgliche Richtungsregel wäre außerdem eine neue, dateninformierte Hypothese und kein unabhängiger Beweis.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(output / "completion.json", {
        "diagnostics_sha256": sha(output / "diagnostics.json"),
        "report_sha256": sha(output / "report.md"),
    })
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose failed dual-horizon TSMOM screen")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, action="append", required=True)
    parser.add_argument("--cost-candidate", type=Path, required=True)
    parser.add_argument("--cost-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        diagnose(args.protocol, args.dataset, args.cost_candidate, args.cost_summary, args.output)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"TSMOM diagnostics failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
