"""Preregistered trailing-exit hypothesis; no tuning and no holdout in this run."""

import argparse
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from backtesting.candidate_research import make_candidate
from backtesting.development import freeze, evaluate
from backtesting.execution import BacktestExecution
from backtesting.net_reward_research import json_value
from backtesting.trailing import SlowUncappedStrategy, TrailingExecution
from backtesting.venue_research import cases

VERSION = "bitvavo-trailing-development-v1"


def variants():
    return {"slow_breakout": (make_candidate("slow_breakout"), "net_reward", BacktestExecution),
            "slow_unfiltered": (make_candidate("slow_breakout"), "original", BacktestExecution),
            "slow_trailing": (SlowUncappedStrategy(), "original", TrailingExecution)}


def definition(market):
    return json_value({"years": [2023, 2024], "timeframe": "4h", "symbol": "BTC/EUR",
        "hypothesis": "Let infrequent trend breakouts capture longer right-tail moves with a causal trailing stop instead of a capped 3R profit target.",
        "variants": {name: {"parameters": asdict(strategy.parameters), "risk_policy": policy,
                            "execution": execution.__name__, "fixed_target": name != "slow_trailing"}
                     for name, (strategy, policy, execution) in variants().items()},
        "settings": {k: asdict(v) for k, v in cases(market).items()},
        "trailing": {"atr_period": 42, "atr_method": "simple", "atr_multiple": "3", "anchor": "highest closed price since entry"},
        "rules": ["Same slow-breakout entry periods and initial 3-ATR stop in all cases; no entry tuning.",
                  "Compare filtered fixed-target control, unfiltered fixed-target control, and unfiltered trailing-only exit. Removing net-target filtering is explicit because an uncapped exit has no fixed reward target.",
                  "Trailing stop is max(previous stop, highest observed close since entry minus 3*ATR42), rounded down. Never loosen a stop.",
                  "A newly calculated stop becomes effective only from the next candle. Never trigger it on an earlier low from its calculation candle.",
                  "If the next open is below the active stop, exit at that open with adverse costs. No gap price guarantee.",
                  "Entry-position stop remains the initial stop; all trailing decisions are appended to exit_updates with their future effective time.",
                  "Current Bitvavo fees/instrument limits on 2023/2024 prices, fixed spread/slippage, LONG 1x, unchanged account risk limits.",
                  "Primary candidate slow_trailing must have positive net and drawdown <10% in both years and both costs, at least 5 normal and 3 stress trades each year.",
                  "Also require slow_trailing to outperform the unfiltered fixed-target control in all four cases. Do not select a fallback winner.",
                  "Exactly one trailing rule. No parameter sweep or modifications after results. All cases reported.",
                  "2023/2024 are already seen development data; trade counts are feasibility thresholds, not significance. 2025 is not loaded or evaluated here.",
                  "No automatic PAPER activation. The running PAPER observer keeps NoTrade."]})


def assess(segments):
    if [s["name"] for s in segments] != ["2023", "2024"]:
        raise ValueError("Exactly two prescribed development years required")
    checks = {}
    for segment in segments:
        indexed = {(r["variant"], r["cost_scenario"]): r["performance"] for r in segment["runs"]}
        expected = {(name, cost) for name in variants() for cost in ("bitvavo_current", "bitvavo_stress")}
        if set(indexed) != expected or len(segment["runs"]) != len(expected):
            raise ValueError("Missing or duplicated comparison case")
        for cost, minimum in (("bitvavo_current", 5), ("bitvavo_stress", 3)):
            candidate, control = indexed["slow_trailing", cost], indexed["slow_unfiltered", cost]
            checks[f"{segment['name']}/{cost}"] = {
                "positive_net": Decimal(candidate["net_profit"]) > 0,
                "enough_trades": type(candidate["trades"]) is int and candidate["trades"] >= minimum,
                "drawdown_below_limit": Decimal(candidate["max_drawdown"]) < Decimal(".10"),
                "beats_fixed_exit": Decimal(candidate["net_profit"]) > Decimal(control["net_profit"])}
    return {"primary": "slow_trailing", "checks": checks,
            "screen_passed": all(all(group.values()) for group in checks.values())}


def main():
    parser = argparse.ArgumentParser(description="Fixed causal trailing-stop development test")
    parser.add_argument("command", choices=("freeze", "evaluate"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.output, args.dataset, args.snapshot, version=VERSION, definition=definition)
    else:
        evaluate(args.output / "protocol.json", args.dataset, args.snapshot, version=VERSION,
                 definition=definition, variants=variants, assess=assess, title="Bitvavo: nachgezogener Stop statt festem Gewinnziel")


if __name__ == "__main__":
    main()
