"""One-shot, fail-closed advancement of frozen PF_XBTUSD studies.

This command creates no schedule and cannot enable PAPER or LIVE. It only
collects already completed public intervals, evaluates a screen once its exact
coverage exists, and refreshes the readiness report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from app.errors import MarketDataError
from app.market_data.kraken_perpetual_forward import collect_due
from app.readiness import DEFAULT_PATHS, ReadinessPaths, build_readiness, write_report
from backtesting.adaptive_forward_research_v2 import evaluate as evaluate_adaptive
from backtesting.perpetual_forward_research import evaluate as evaluate_primary
from backtesting.profit_protection_forward_research_v3 import evaluate as evaluate_protection


Evaluator = Callable[[], object]


def _default_evaluators(paths: ReadinessPaths) -> dict[str, Evaluator]:
    return {
        "primary": lambda: evaluate_primary(
            paths.protocol, paths.forward_root, paths.cost_candidate,
            paths.cost_summary, "screen",
        ),
        "adaptive_v2": lambda: evaluate_adaptive(
            paths.adaptive_protocol, paths.forward_root, paths.cost_candidate,
            paths.cost_summary, "screen",
        ),
        "profit_protection_v3": lambda: evaluate_protection(
            paths.profit_protection_protocol, paths.forward_root,
            paths.cost_candidate, paths.cost_summary, "screen",
        ),
    }


def evaluate_ready_screens(
    report: dict,
    paths: ReadinessPaths = DEFAULT_PATHS,
    *,
    evaluators: dict[str, Evaluator] | None = None,
) -> tuple[str, ...]:
    """Evaluate each frozen screen once, only after its exact minimum is present."""
    gates = report.get("gates")
    if not isinstance(gates, dict) or report.get("live_enabled") is not False:
        raise ValueError("Readiness report is invalid or unsafe")
    configured = evaluators or _default_evaluators(paths)
    expected = {"primary", "adaptive_v2", "profit_protection_v3"}
    if set(configured) != expected:
        raise ValueError("Screen evaluator set differs")

    primary = gates.get("forward", {}).get("screen", {})
    adaptive = gates.get("adaptive_candidate", {})
    protection = gates.get("profit_protection_candidate", {})
    candidates = (
        ("primary", primary, gates.get("screen", {}).get("status"),
         paths.protocol.parent / "screen"),
        ("adaptive_v2", adaptive, adaptive.get("screen", {}).get("status", "not_evaluated"),
         paths.adaptive_protocol.parent / "screen"),
        ("profit_protection_v3", protection,
         protection.get("screen", {}).get("status", "not_evaluated"),
         paths.profit_protection_protocol.parent / "screen"),
    )
    completed = []
    for name, progress, status, output in candidates:
        collected, required = progress.get("collected"), progress.get("required")
        if (type(collected) is not int or type(required) is not int
                or collected < 0 or required <= 0 or collected > required):
            raise ValueError(f"{name} screen progress is invalid")
        if collected == required and status == "not_evaluated" and not output.exists():
            configured[name]()
            completed.append(name)
    return tuple(completed)


def advance(*, output: Path, max_intervals: int = 42,
            collect: bool = True, paths: ReadinessPaths = DEFAULT_PATHS) -> dict:
    created = (collect_due(paths.forward_root, max_intervals=max_intervals)
               if collect else ())
    before = build_readiness(paths)
    evaluated = evaluate_ready_screens(before, paths)
    after = build_readiness(paths)
    write_report(output, after)
    return {
        "created_bundles": [path.name for path in created],
        "evaluated_screens": list(evaluated),
        "overall_status": after["overall_status"],
        "profitability_proven": after["profitability_proven"],
        "paper_candidate": after["paper_candidate"],
        "live_enabled": False,
        "blockers": after["blockers"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Advance frozen studies once; creates no schedule and never enables LIVE"
    )
    parser.add_argument("--output", type=Path, default=Path("data/readiness/status.json"))
    parser.add_argument("--max-intervals", type=int, default=42)
    parser.add_argument("--skip-collection", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = advance(
            output=args.output, max_intervals=args.max_intervals,
            collect=not args.skip_collection,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, MarketDataError) as exc:
        print(f"Study advancement failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
