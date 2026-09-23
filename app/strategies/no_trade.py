"""Neutral placeholder, deliberately not a trading strategy."""

from decimal import Decimal
from typing import Sequence

from app.domain import Direction
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.models import Signal


class NoTradeStrategy(Strategy):
    def analyze(self, history: Sequence[Candle]) -> Signal:
        if not history:
            raise ValueError("At least one closed candle is required")
        candle = history[-1]
        return Signal(candle.symbol, candle.closed_at, Direction.HOLD, Decimal("0"),
                      ("No trading strategy has been configured.",), "no_trade", "0.1.0")
