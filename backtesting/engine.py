"""Chronological next-bar simulation without access to future candles."""

from dataclasses import dataclass
from typing import Sequence

from app.market_data.models import Candle
from app.market_data.quality import require_complete
from app.strategies.base import Strategy
from backtesting.execution import BacktestExecution
from backtesting.metrics import Performance, calculate_performance
from backtesting.history import CandleHistory


@dataclass(frozen=True)
class ReplayResult:
    candles_processed: int
    signals_recorded: int
    performance: Performance


class Backtester:
    """Signals from candle close are considered only at the following candle open."""

    def __init__(self, strategy: Strategy, execution: BacktestExecution) -> None:
        self.strategy = strategy
        self.execution = execution

    def run(self, candles: Sequence[Candle], *, warmup: Sequence[Candle] = ()) -> ReplayResult:
        # Validate the entire input before producing any persisted output.
        require_complete(candles)
        if warmup:
            require_complete(warmup)
            if (warmup[-1].closed_at != candles[0].timestamp
                    or (warmup[-1].symbol, warmup[-1].timeframe) != (candles[0].symbol, candles[0].timeframe)):
                raise ValueError("Warm-up must directly precede the evaluated data in the same market")
        observed = tuple(warmup) + tuple(candles)
        pending = None
        for index, candle in enumerate(candles):
            self.execution.on_bar(candle, pending)
            history = CandleHistory(observed, len(warmup) + index + 1)
            signal = self.strategy.analyze(history)
            if signal.symbol != candle.symbol or signal.timestamp != candle.closed_at:
                raise ValueError("Signals must match the current symbol and candle close time")
            pending = signal
        self.execution.record_unexecuted(pending)
        self.execution.finish(candles[-1])
        broker = self.execution.broker
        performance = calculate_performance(broker.settings.initial_capital, broker.snapshot().cash,
                                             broker.trades, self.execution.equity_curve, broker.total_fees)
        return ReplayResult(len(candles), len(candles), performance)
