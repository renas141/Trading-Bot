"""Fixed, symmetric slow-breakout hypothesis with causal regime filters."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.domain import Direction, positive_decimal
from app.indicators.core import average_true_range, mean
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.models import Signal


@dataclass(frozen=True)
class RegimeBreakoutParameters:
    trend_period: int = 600
    trend_slope_period: int = 30
    breakout_period: int = 120
    efficiency_period: int = 60
    atr_period: int = 42
    volume_period: int = 30
    minimum_efficiency: Decimal = Decimal("0.25")
    minimum_atr_fraction: Decimal = Decimal("0.005")
    maximum_atr_fraction: Decimal = Decimal("0.04")
    volume_multiplier: Decimal = Decimal("1")
    stop_atr_multiple: Decimal = Decimal("3")
    reward_risk_multiple: Decimal = Decimal("3")
    requested_leverage: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        for name in ("trend_period", "trend_slope_period", "breakout_period",
                     "efficiency_period", "atr_period", "volume_period"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("minimum_efficiency", "minimum_atr_fraction", "maximum_atr_fraction",
                     "volume_multiplier", "stop_atr_multiple", "reward_risk_multiple",
                     "requested_leverage"):
            positive_decimal(getattr(self, name), name)
        if not self.minimum_atr_fraction < self.maximum_atr_fraction:
            raise ValueError("ATR fraction range is invalid")
        if self.minimum_efficiency > 1 or self.requested_leverage > 10:
            raise ValueError("Efficiency and leverage caps are exceeded")

    @property
    def required_history(self) -> int:
        return max(self.trend_period + self.trend_slope_period,
                   self.breakout_period + 1, self.efficiency_period + 1,
                   self.atr_period + 1, self.volume_period + 1)


class RegimeBreakoutStrategy(Strategy):
    """Trade only directional breakouts in persistent, liquid, moderate-volatility regimes."""

    name = "regime_breakout_perpetual"
    version = "0.1.0"

    def __init__(self, parameters: RegimeBreakoutParameters | None = None) -> None:
        self.parameters = parameters or RegimeBreakoutParameters()

    def analyze(self, history: Sequence[Candle]) -> Signal:
        if not history:
            raise ValueError("At least one closed candle is required")
        current, p = history[-1], self.parameters
        if len(history) < p.required_history:
            return Signal(current.symbol, current.closed_at, Direction.HOLD, Decimal("0"),
                          (f"Warm-up: {len(history)}/{p.required_history} closed candles.",),
                          self.name, self.version)
        window = history[-p.required_history:]
        if any((c.symbol, c.timeframe) != (current.symbol, current.timeframe) for c in window):
            raise ValueError("Strategy requires one symbol and timeframe")
        closes = [c.close for c in window]
        trend = mean(closes[-p.trend_period:])
        prior_trend = mean(closes[-p.trend_period - p.trend_slope_period:-p.trend_slope_period])
        prior_high = max(c.high for c in window[-p.breakout_period - 1:-1])
        prior_low = min(c.low for c in window[-p.breakout_period - 1:-1])
        path = sum((abs(a - b) for a, b in zip(closes[-p.efficiency_period - 1:-1],
                                                closes[-p.efficiency_period:])), Decimal("0"))
        efficiency = abs(closes[-1] - closes[-p.efficiency_period - 1]) / path if path else Decimal("0")
        atr = average_true_range(window, p.atr_period)
        atr_fraction = atr / current.close
        prior_volume = mean([c.volume for c in window[-p.volume_period - 1:-1]])
        common = (
            (efficiency >= p.minimum_efficiency,
             f"Efficiency={efficiency} >= {p.minimum_efficiency}"),
            (p.minimum_atr_fraction <= atr_fraction <= p.maximum_atr_fraction,
             f"ATR/close={atr_fraction} inside [{p.minimum_atr_fraction},{p.maximum_atr_fraction}]"),
            (prior_volume > 0 and current.volume >= prior_volume * p.volume_multiplier,
             f"Volume={current.volume}, prior mean={prior_volume}"),
        )
        long_checks = (
            (current.close > trend and trend > prior_trend,
             f"LONG trend: close={current.close}, SMA={trend}, prior_SMA={prior_trend}"),
            (current.close > prior_high,
             f"LONG breakout: close={current.close}, prior_high={prior_high}"),
        ) + common
        short_checks = (
            (current.close < trend and trend < prior_trend,
             f"SHORT trend: close={current.close}, SMA={trend}, prior_SMA={prior_trend}"),
            (current.close < prior_low,
             f"SHORT breakout: close={current.close}, prior_low={prior_low}"),
        ) + common
        if all(value for value, _ in long_checks):
            direction, checks = Direction.LONG, long_checks
        elif all(value for value, _ in short_checks):
            direction, checks = Direction.SHORT, short_checks
        else:
            direction = Direction.HOLD
            checks = long_checks if sum(v for v, _ in long_checks) >= sum(v for v, _ in short_checks) else short_checks
        reasons = tuple(f"{'PASS' if value else 'FAIL'} {reason}" for value, reason in checks)
        score = Decimal(sum(value for value, _ in checks)) / len(checks)
        if direction == Direction.HOLD or atr <= 0:
            return Signal(current.symbol, current.closed_at, Direction.HOLD, score,
                          reasons + ("Confidence is a rule score, not a win probability.",),
                          self.name, self.version)
        distance = atr * p.stop_atr_multiple
        stop = current.close - distance if direction == Direction.LONG else current.close + distance
        target = (current.close + distance * p.reward_risk_multiple if direction == Direction.LONG
                  else current.close - distance * p.reward_risk_multiple)
        if stop <= 0 or target <= 0:
            return Signal(current.symbol, current.closed_at, Direction.HOLD, score,
                          reasons + ("ATR geometry is not positive.",), self.name, self.version)
        return Signal(current.symbol, current.closed_at, direction, score,
                      reasons + ("Confidence is a rule score, not a win probability.",),
                      self.name, self.version, stop, target, p.requested_leverage)
