"""Forward-only momentum with delayed regime and funding-pressure confirmation."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Mapping, Sequence

from app.domain import Direction, aware_timestamp, positive_decimal
from app.indicators.core import average_true_range
from app.market_data.models import Candle
from app.market_data.perpetual_regime_alignment import AlignedRegimeBar
from app.strategies.base import Strategy
from app.strategies.models import Signal


@dataclass(frozen=True)
class FundingAwareRegimeMomentumParameters:
    fast_momentum_bars: int = 12       # 2 days on 4h candles
    slow_momentum_bars: int = 42       # 7 days on 4h candles
    regime_change_bars: int = 42       # 7-day OI/CVD change
    funding_average_bars: int = 6      # preceding 24 hours
    atr_period: int = 42               # 7 days
    stop_atr_multiple: Decimal = Decimal("3")
    requested_leverage: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        for name in ("fast_momentum_bars", "slow_momentum_bars",
                     "regime_change_bars", "funding_average_bars", "atr_period"):
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
        return max(self.slow_momentum_bars + 1, self.regime_change_bars + 1,
                   self.funding_average_bars + 1, self.atr_period + 1)


class FundingAwareRegimeMomentumStrategy(Strategy):
    """Trade price/flow agreement only while directional funding pressure eases."""

    name = "funding_aware_regime_momentum_perpetual"
    version = "0.1.1"

    def __init__(self, aligned: Sequence[AlignedRegimeBar],
                 funding_by_candle: Mapping[datetime, Decimal],
                 parameters: FundingAwareRegimeMomentumParameters | None = None) -> None:
        self.parameters = parameters or FundingAwareRegimeMomentumParameters()
        self._regime = {}
        for bar in aligned:
            timestamp = bar.trade.timestamp
            if timestamp in self._regime:
                raise ValueError("Aligned regime input has duplicate candle timestamps")
            if bar.regime_completed_at > timestamp:
                raise ValueError("Aligned regime input is not available before its candle")
            self._regime[timestamp] = bar.regime
        self._funding = {}
        for timestamp, rate in funding_by_candle.items():
            if not isinstance(timestamp, datetime):
                raise ValueError("Funding input requires aware timestamps and finite Decimals")
            aware_timestamp(timestamp)
            if (timestamp.utcoffset() != timedelta(0) or timestamp.microsecond
                    or int(timestamp.timestamp()) % (4 * 60 * 60)
                    or not isinstance(rate, Decimal) or not rate.is_finite()):
                raise ValueError("Funding input requires aware timestamps and finite Decimals")
            if timestamp in self._funding:
                raise ValueError("Funding input has duplicate candle timestamps")
            self._funding[timestamp] = rate

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
                f"FAIL agreeing 2-day/7-day returns: {fast_return}/{slow_return}.",
                "Regime and funding checks are not evaluated without an agreed direction.",
            ))

        past_timestamp = history[-p.regime_change_bars - 1].timestamp
        current_regime = self._regime.get(current.timestamp)
        past_regime = self._regime.get(past_timestamp)
        funding_window = window[-p.funding_average_bars - 1:]
        funding = [self._funding.get(candle.timestamp) for candle in funding_window]
        if current_regime is None or past_regime is None or any(rate is None for rate in funding):
            return self._hold(current, Decimal("0.25"), (
                "Price trend agrees, but delayed regime or funding history is incomplete.",
            ))
        if past_regime["open_interest"] <= 0:
            return self._hold(current, Decimal("0.25"), (
                "Price trend agrees, but the open-interest comparison base is not positive.",
            ))

        sign = Decimal("1") if direction == Direction.LONG else Decimal("-1")
        open_interest_change = current_regime["open_interest"] / past_regime["open_interest"] - 1
        cvd_change = (current_regime["cumulative_volume_delta"]
                      - past_regime["cumulative_volume_delta"])
        aggressor = current_regime["aggressor_differential"]
        directional_current_funding = sign * funding[-1]
        directional_prior_average = (
            sign * sum(funding[:-1], Decimal("0")) / Decimal(p.funding_average_bars)
        )
        checks = (
            (open_interest_change > 0, f"7-day open-interest change={open_interest_change}"),
            (sign * aggressor > 0, f"directional aggressor differential={sign * aggressor}"),
            (sign * cvd_change > 0, f"directional 7-day CVD change={sign * cvd_change}"),
            (directional_current_funding <= directional_prior_average,
             f"directional current funding={directional_current_funding} versus prior-24h "
             f"average={directional_prior_average}"),
        )
        passed = sum(ok for ok, _ in checks)
        score = Decimal(2 + passed) / Decimal("6")
        reasons = (
            f"PASS agreeing 2-day/7-day returns: {fast_return}/{slow_return}.",
            *(f"{'PASS' if ok else 'FAIL'} {detail}." for ok, detail in checks),
            "Regime inputs use a full completed-bucket safety delay.",
            "Funding compares completed intervals and uses no fitted threshold.",
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
        return Signal(
            current.symbol, current.closed_at, direction, score,
            reasons + (f"ATR({p.atr_period})={atr}; stop multiple={p.stop_atr_multiple}.",),
            self.name, self.version, stop, None, p.requested_leverage,
        )
