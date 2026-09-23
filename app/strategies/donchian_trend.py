"""Simple long-only Donchian trend hypothesis for perpetual research."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.domain import Direction, positive_decimal
from app.indicators.core import average_true_range, mean
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.models import Signal


@dataclass(frozen=True)
class DonchianTrendParameters:
    trend_period: int = 600
    trend_slope_period: int = 30
    breakout_period: int = 120
    atr_period: int = 42
    stop_atr_multiple: Decimal = Decimal("3")
    requested_leverage: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        for name in ("trend_period", "trend_slope_period", "breakout_period", "atr_period"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 2:
                raise ValueError(f"{name} must be an integer of at least two")
        positive_decimal(self.stop_atr_multiple, "stop_atr_multiple")
        positive_decimal(self.requested_leverage, "requested_leverage")
        if self.requested_leverage > 10:
            raise ValueError("Requested leverage exceeds the research cap")

    @property
    def required_history(self) -> int:
        return max(self.trend_period + self.trend_slope_period,
                   self.breakout_period + 1, self.atr_period + 1)


class DonchianTrendStrategy(Strategy):
    """Enter a 20-day high only while the 100-day mean is rising; LONG only."""

    name = "donchian_long_perpetual"
    version = "0.1.0"

    def __init__(self, parameters: DonchianTrendParameters | None = None) -> None:
        self.parameters = parameters or DonchianTrendParameters()

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
        atr = average_true_range(window, p.atr_period)
        checks = (
            (current.close > trend and trend > prior_trend,
             f"LONG trend: close={current.close}, SMA={trend}, prior_SMA={prior_trend}"),
            (current.close > prior_high,
             f"20-day breakout: close={current.close}, prior_high={prior_high}"),
        )
        reasons = tuple(f"{'PASS' if passed else 'FAIL'} {detail}" for passed, detail in checks)
        score = Decimal(sum(passed for passed, _ in checks)) / Decimal(len(checks))
        stop = current.close - atr * p.stop_atr_multiple
        allowed = all(passed for passed, _ in checks) and atr > 0 and stop > 0
        reasons += (f"ATR(simple)={atr}; initial stop distance={current.close - stop}.",
                    "No fixed target; a separate causal ATR trailing policy manages exits.",
                    "Confidence is a rule score, not a win probability.")
        return Signal(current.symbol, current.closed_at,
                      Direction.LONG if allowed else Direction.HOLD, score, reasons,
                      self.name, self.version, stop if allowed else None, None,
                      p.requested_leverage)
