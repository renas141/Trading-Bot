"""Explicit strategy selection; the safe default remains no_trade."""

from dataclasses import asdict

from app.strategies.base import Strategy
from app.strategies.no_trade import NoTradeStrategy
from app.strategies.trend_breakout import TrendBreakoutStrategy

STRATEGIES = ("no_trade", "trend_breakout")


def make_strategy(name: str) -> Strategy:
    if name == "no_trade":
        return NoTradeStrategy()
    if name == "trend_breakout":
        return TrendBreakoutStrategy()
    raise ValueError("Unknown strategy")


def strategy_metadata(name: str) -> dict[str, object]:
    strategy = make_strategy(name)
    if isinstance(strategy, TrendBreakoutStrategy):
        return {"name": name, "version": strategy.version,
                "parameters": {key: str(value) if not isinstance(value, int) else value
                               for key, value in asdict(strategy.parameters).items()},
                "confidence_semantics": "fraction_of_conditions_passed_not_probability"}
    return {"name": name, "version": "0.1.0", "parameters": {}}
