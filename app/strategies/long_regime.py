"""Data-informed structural-bias hypothesis built after symmetric v1 failed."""

from dataclasses import replace
from typing import Sequence

from app.domain import Direction
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.models import Signal
from app.strategies.regime_breakout import RegimeBreakoutStrategy


class LongOnlyRegimeStrategy(Strategy):
    name = "long_only_regime_breakout_perpetual"
    version = "0.1.0"

    def __init__(self, base: Strategy | None = None) -> None:
        self.base = base or RegimeBreakoutStrategy()
        self.parameters = self.base.parameters

    def analyze(self, history: Sequence[Candle]) -> Signal:
        signal = self.base.analyze(history)
        if signal.direction != Direction.SHORT:
            return replace(signal, strategy=self.name, strategy_version=self.version)
        return replace(
            signal,
            direction=Direction.HOLD,
            stop_price=None,
            take_profit_price=None,
            strategy=self.name,
            strategy_version=self.version,
            reasons=signal.reasons + (
                "SHORT suppressed by the preregistered long-only structural-bias hypothesis.",
            ),
        )


class UncappedLongOnlyRegimeStrategy(LongOnlyRegimeStrategy):
    """Same fixed entry and initial stop, with profit-taking delegated to an exit policy."""

    name = "uncapped_long_only_regime_breakout_perpetual"
    version = "0.1.0"

    def analyze(self, history: Sequence[Candle]) -> Signal:
        signal = super().analyze(history)
        return replace(
            signal,
            take_profit_price=None,
            strategy=self.name,
            strategy_version=self.version,
            reasons=signal.reasons + ("No fixed target; a separate trailing policy manages exits.",),
        )
