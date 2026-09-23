"""Small, deterministic Decimal indicators, with explicit lookback definitions."""

from decimal import Decimal
from typing import Sequence

from app.market_data.models import Candle


def mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("Mean requires at least one observation")
    return sum(values, Decimal("0")) / len(values)


def average_true_range(candles: Sequence[Candle], period: int) -> Decimal:
    """Simple mean of true ranges (not Wilder's recursive smoothing)."""
    if type(period) is not int or period < 1 or len(candles) < period + 1:
        raise ValueError("ATR requires period+1 candles and a positive integer period")
    window = candles[-(period + 1):]
    ranges = [max(current.high - current.low, abs(current.high - previous.close),
                  abs(current.low - previous.close)) for previous, current in zip(window, window[1:])]
    return mean(ranges)
