"""Fixed momentum rule confirmed by delayed perpetual regime analytics."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.domain import Direction, positive_decimal
from app.indicators.core import average_true_range
from app.market_data.models import Candle
from app.market_data.perpetual_regime_alignment import AlignedRegimeBar
from app.strategies.base import Strategy
from app.strategies.models import Signal


@dataclass(frozen=True)
class RegimeConfirmedMomentumParameters:
    fast_momentum_bars: int = 42
    slow_momentum_bars: int = 168
    regime_change_bars: int = 42
    atr_period: int = 42
    stop_atr_multiple: Decimal = Decimal("3")
    requested_leverage: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        for name in ("fast_momentum_bars", "slow_momentum_bars",
                     "regime_change_bars", "atr_period"):
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


class RegimeConfirmedMomentumStrategy(Strategy):
    """Trade fixed price momentum only with rising OI and agreeing order flow."""

    name = "regime_confirmed_momentum_perpetual"
    version = "0.1.0"

    def __init__(self, aligned: Sequence[AlignedRegimeBar],
                 parameters: RegimeConfirmedMomentumParameters | None = None) -> None:
        self.parameters = parameters or RegimeConfirmedMomentumParameters()
        self._regime = {}
        for bar in aligned:
            timestamp = bar.trade.timestamp
            if timestamp in self._regime:
                raise ValueError("Aligned regime input has duplicate candle timestamps")
            if bar.regime_completed_at > timestamp:
                raise ValueError("Aligned regime input is not available before its candle")
            self._regime[timestamp] = bar.regime

    def _hold(self, current: Candle, score: Decimal, reasons: tuple[str, ...]) -> Signal:
        return Signal(current.symbol, current.closed_at, Direction.HOLD, score, reasons,
                      self.name, self.version)

    def analyze(self, history: Sequence[Candle]) -> Signal:
        if not history:
            raise ValueError("At least one closed candle is required")
        current, p = history[-1], self.parameters
        if len(history) < p.required_history:
            return self._hold(
                current, Decimal("0"),
                (f"Warm-up: {len(history)}/{p.required_history} closed candles.",),
            )
        window = history[-p.required_history:]
        if any((c.symbol, c.timeframe) != (current.symbol, current.timeframe) for c in window):
            raise ValueError("Strategy requires one symbol and timeframe")

        fast_return = current.close / window[-p.fast_momentum_bars - 1].close - 1
        slow_return = current.close / window[-p.slow_momentum_bars - 1].close - 1
        if fast_return > 0 and slow_return > 0:
            direction = Direction.LONG
        elif fast_return < 0 and slow_return < 0:
            direction = Direction.SHORT
        else:
            return self._hold(current, Decimal("0.25"), (
                f"FAIL agreeing 7-day/28-day returns: {fast_return}/{slow_return}.",
                "Regime filters are not evaluated without an agreed price direction.",
            ))

        past_timestamp = history[-p.regime_change_bars - 1].timestamp
        current_regime = self._regime.get(current.timestamp)
        past_regime = self._regime.get(past_timestamp)
        if current_regime is None or past_regime is None:
            return self._hold(current, Decimal("0.25"), (
                "Price trend agrees, but delayed regime history is incomplete.",
            ))

        sign = Decimal("1") if direction == Direction.LONG else Decimal("-1")
        open_interest_change = (
            current_regime["open_interest"] / past_regime["open_interest"] - 1
        )
        cvd_change = (
            current_regime["cumulative_volume_delta"]
            - past_regime["cumulative_volume_delta"]
        )
        aggressor = current_regime["aggressor_differential"]
        checks = (
            (open_interest_change > 0, f"7-day open-interest change={open_interest_change}"),
            (sign * aggressor > 0, f"directional aggressor differential={sign * aggressor}"),
            (sign * cvd_change > 0, f"directional 7-day CVD change={sign * cvd_change}"),
        )
        passed = sum(ok for ok, _ in checks)
        score = Decimal(2 + passed) / Decimal("5")
        reasons = (
            f"PASS agreeing 7-day/28-day returns: {fast_return}/{slow_return}.",
            *(f"{'PASS' if ok else 'FAIL'} {detail}." for ok, detail in checks),
            "Regime inputs have a full completed-bucket safety delay.",
            "Confidence is rule agreement, not a win probability.",
        )
        if passed != len(checks):
            return self._hold(current, score, reasons)

        atr = average_true_range(window, p.atr_period)
        if atr <= 0:
            return self._hold(current, score, reasons + ("ATR is not positive.",))
        distance = atr * p.stop_atr_multiple
        stop = current.close - distance if direction == Direction.LONG else current.close + distance
        if stop <= 0:
            return self._hold(current, score, reasons + ("ATR stop geometry is not positive.",))
        return Signal(current.symbol, current.closed_at, direction, score,
                      reasons + (f"ATR({p.atr_period})={atr}; stop multiple={p.stop_atr_multiple}.",),
                      self.name, self.version, stop, None, p.requested_leverage)
