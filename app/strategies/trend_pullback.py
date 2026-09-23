"""Fixed research-only slow trend/pullback hypothesis; no calibrated probability."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.domain import Direction
from app.indicators.core import average_true_range, mean
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.models import Signal


@dataclass(frozen=True)
class PullbackParameters:
    trend_period: int = 300
    pullback_period: int = 30
    atr_period: int = 42
    volume_period: int = 30
    stop_atr_multiple: Decimal = Decimal("3")
    reward_risk_multiple: Decimal = Decimal("3")

    def __post_init__(self):
        if any(type(v) is not int or not 2 <= v <= 10000 for v in
               (self.trend_period, self.pullback_period, self.atr_period, self.volume_period)):
            raise ValueError("Invalid indicator period")
        if any(not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in (self.stop_atr_multiple, self.reward_risk_multiple)):
            raise ValueError("Positive finite stop and reward multiples required")

    @property
    def required_history(self):
        return max(self.trend_period, self.pullback_period, self.atr_period, self.volume_period) + 1


class TrendPullbackStrategy(Strategy):
    name, version = "trend_pullback", "0.1.0"

    def __init__(self, parameters=None):
        self.parameters = parameters or PullbackParameters()

    def analyze(self, history: Sequence[Candle]) -> Signal:
        if not history:
            raise ValueError("Closed candle required")
        current, p = history[-1], self.parameters
        if len(history) < p.required_history:
            return Signal(current.symbol, current.closed_at, Direction.HOLD, Decimal(0),
                          (f"Warm-up: {len(history)}/{p.required_history} closed candles available.",), self.name, self.version)
        window = history[-p.required_history:]
        if any((c.symbol, c.timeframe) != (current.symbol, current.timeframe) for c in window):
            raise ValueError("Mixed strategy history")
        prices = [c.close for c in window]
        slow, previous_slow = mean(prices[-p.trend_period:]), mean(prices[-p.trend_period - 1:-1])
        fast, previous_fast = mean(prices[-p.pullback_period:]), mean(prices[-p.pullback_period - 1:-1])
        volume = mean([c.volume for c in window[-p.volume_period - 1:-1]])
        checks = ((current.close > slow and slow > previous_slow, f"Trend: close={current.close}, SMA={slow}, prior_SMA={previous_slow}"),
                  (prices[-2] <= previous_fast and current.close > fast, f"Pullback: prior_close={prices[-2]}, prior_SMA={previous_fast}, close={current.close}, SMA={fast}"),
                  (current.close > window[-2].high, f"Momentum: close={current.close}, prior_high={window[-2].high}"),
                  (volume > 0 and current.volume >= volume, f"Volume: current={current.volume}, prior_mean={volume}"))
        atr = average_true_range(window, p.atr_period)
        stop = current.close - p.stop_atr_multiple * atr
        allowed = all(passed for passed, _ in checks) and atr > 0 and stop > 0
        reasons = tuple(f"{'PASS' if passed else 'FAIL'} {detail}" for passed, detail in checks)
        reasons += (f"ATR(simple)={atr}; stop_distance={current.close - stop}.",
                    "Confidence is the fraction of passed conditions, not a calibrated win probability.")
        return Signal(current.symbol, current.closed_at, Direction.LONG if allowed else Direction.HOLD,
                      Decimal(sum(passed for passed, _ in checks)) / len(checks), reasons, self.name, self.version,
                      stop_price=stop if allowed else None,
                      take_profit_price=current.close + (current.close - stop) * p.reward_risk_multiple if allowed else None)
