"""Untuned research hypothesis: confirmed breakout with trend, momentum and volume."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.domain import Direction, positive_decimal
from app.indicators.core import average_true_range, mean
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.models import Signal


@dataclass(frozen=True)
class TrendBreakoutParameters:
    trend_period: int = 50
    breakout_period: int = 20
    volume_period: int = 20
    momentum_period: int = 5
    atr_period: int = 14
    volume_multiplier: Decimal = Decimal("1.2")
    stop_atr_multiple: Decimal = Decimal("2")
    reward_risk_multiple: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        for name in ("trend_period", "breakout_period", "volume_period", "momentum_period", "atr_period"):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= 10000:
                raise ValueError(f"{name} must be an integer in 1..10000")
        for name in ("volume_multiplier", "stop_atr_multiple", "reward_risk_multiple"):
            positive_decimal(getattr(self, name), name)

    @property
    def required_history(self) -> int:
        return max(self.trend_period, self.breakout_period, self.volume_period,
                   self.momentum_period, self.atr_period) + 1


class TrendBreakoutStrategy(Strategy):
    name = "trend_breakout"
    version = "0.1.0"

    def __init__(self, parameters: TrendBreakoutParameters | None = None) -> None:
        self.parameters = parameters or TrendBreakoutParameters()

    def analyze(self, history: Sequence[Candle]) -> Signal:
        if not history:
            raise ValueError("At least one closed candle is required")
        current, p = history[-1], self.parameters
        if len(history) < p.required_history:
            return Signal(current.symbol, current.closed_at, Direction.HOLD, Decimal("0"),
                          (f"Warm-up: {len(history)}/{p.required_history} closed candles available.",),
                          self.name, self.version)
        window = history[-p.required_history:]
        if any((c.symbol, c.timeframe) != (current.symbol, current.timeframe) for c in window):
            raise ValueError("Strategy requires one symbol and timeframe")
        closes = [c.close for c in window]
        sma = mean(closes[-p.trend_period:])
        previous_sma = mean(closes[-p.trend_period - 1:-1])
        prior_high = max(c.high for c in window[-p.breakout_period - 1:-1])
        prior_volume = mean([c.volume for c in window[-p.volume_period - 1:-1]])
        momentum_base = closes[-p.momentum_period - 1]
        atr = average_true_range(window, p.atr_period)
        checks = (
            (current.close > sma and sma > previous_sma,
             f"Trend: close={current.close}, SMA={sma}, prior_SMA={previous_sma}"),
            (current.close > prior_high, f"Breakout: close={current.close}, prior_high={prior_high}"),
            (current.close > momentum_base, f"Momentum: close={current.close}, prior_close={momentum_base}"),
            (prior_volume > 0 and current.volume >= prior_volume * p.volume_multiplier,
             f"Volume: current={current.volume}, prior_mean={prior_volume}, multiplier={p.volume_multiplier}"),
        )
        reasons = tuple(f"{'PASS' if passed else 'FAIL'} {explanation}" for passed, explanation in checks)
        score = Decimal(sum(passed for passed, _ in checks)) / len(checks)
        stop_distance = atr * p.stop_atr_multiple
        stop = current.close - stop_distance
        valid_stop = atr > 0 and stop > 0
        allowed = all(passed for passed, _ in checks) and valid_stop
        reasons += (f"ATR(simple)={atr}; stop_distance={stop_distance}.",
                    "Confidence is the fraction of passed conditions, not a calibrated win probability.")
        if not valid_stop:
            reasons += ("No valid positive ATR-based stop available.",)
        return Signal(current.symbol, current.closed_at, Direction.LONG if allowed else Direction.HOLD,
                      score, reasons, self.name, self.version,
                      stop_price=stop if allowed else None,
                      take_profit_price=current.close + (current.close - stop) * p.reward_risk_multiple if allowed else None)
