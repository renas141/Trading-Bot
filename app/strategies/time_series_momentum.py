"""Fixed dual-horizon time-series momentum for perpetual research."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.domain import Direction, positive_decimal
from app.indicators.core import average_true_range
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.models import Signal


@dataclass(frozen=True)
class TimeSeriesMomentumParameters:
    fast_momentum_bars: int = 180   # 30 days on 4h candles
    slow_momentum_bars: int = 720   # 120 days on 4h candles
    atr_period: int = 84            # 14 days on 4h candles
    stop_atr_multiple: Decimal = Decimal("4")
    requested_leverage: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        for name in ("fast_momentum_bars", "slow_momentum_bars", "atr_period"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 2:
                raise ValueError(f"{name} must be an integer of at least two")
        if self.fast_momentum_bars >= self.slow_momentum_bars:
            raise ValueError("Fast momentum must be shorter than slow momentum")
        positive_decimal(self.stop_atr_multiple, "stop_atr_multiple")
        positive_decimal(self.requested_leverage, "requested_leverage")
        if self.requested_leverage > 10:
            raise ValueError("Requested leverage exceeds the research cap")

    @property
    def required_history(self) -> int:
        return max(self.slow_momentum_bars + 1, self.atr_period + 1)


class TimeSeriesMomentumStrategy(Strategy):
    """Follow only agreement between fixed 30-day and 120-day own-price returns."""

    name = "dual_horizon_tsmom_perpetual"
    version = "0.1.0"

    def __init__(self, parameters: TimeSeriesMomentumParameters | None = None) -> None:
        self.parameters = parameters or TimeSeriesMomentumParameters()

    def analyze(self, history: Sequence[Candle]) -> Signal:
        if not history:
            raise ValueError("At least one closed candle is required")
        current, p = history[-1], self.parameters
        if len(history) < p.required_history:
            return Signal(
                current.symbol, current.closed_at, Direction.HOLD, Decimal("0"),
                (f"Warm-up: {len(history)}/{p.required_history} closed candles.",),
                self.name, self.version,
            )
        window = history[-p.required_history:]
        if any((c.symbol, c.timeframe) != (current.symbol, current.timeframe) for c in window):
            raise ValueError("Strategy requires one symbol and timeframe")
        fast_base = window[-p.fast_momentum_bars - 1].close
        slow_base = window[-p.slow_momentum_bars - 1].close
        fast_return = current.close / fast_base - 1
        slow_return = current.close / slow_base - 1
        long_checks = ((fast_return > 0, f"30-day return={fast_return}"),
                       (slow_return > 0, f"120-day return={slow_return}"))
        short_checks = ((fast_return < 0, f"30-day return={fast_return}"),
                        (slow_return < 0, f"120-day return={slow_return}"))
        if all(passed for passed, _ in long_checks):
            direction, checks = Direction.LONG, long_checks
        elif all(passed for passed, _ in short_checks):
            direction, checks = Direction.SHORT, short_checks
        else:
            direction = Direction.HOLD
            checks = long_checks if sum(passed for passed, _ in long_checks) >= 1 else short_checks
        reasons = tuple(f"{'PASS' if passed else 'FAIL'} {detail}" for passed, detail in checks)
        score = Decimal(sum(passed for passed, _ in checks)) / Decimal(len(checks))
        atr = average_true_range(window, p.atr_period)
        reasons += (
            f"ATR(simple,{p.atr_period})={atr}; stop multiple={p.stop_atr_multiple}.",
            "No fixed target; a separate close-confirmed ATR trailing policy manages exits.",
            "Confidence is rule agreement, not a win probability.",
        )
        if direction == Direction.HOLD or atr <= 0:
            return Signal(current.symbol, current.closed_at, Direction.HOLD, score, reasons,
                          self.name, self.version)
        distance = atr * p.stop_atr_multiple
        stop = current.close - distance if direction == Direction.LONG else current.close + distance
        if stop <= 0:
            return Signal(current.symbol, current.closed_at, Direction.HOLD, score,
                          reasons + ("ATR stop geometry is not positive.",),
                          self.name, self.version)
        return Signal(current.symbol, current.closed_at, direction, score, reasons,
                      self.name, self.version, stop, None, p.requested_leverage)
