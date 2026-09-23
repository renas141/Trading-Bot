"""Explicit empty-interval replay: expire entries, keep risk and positions alive."""

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from app.domain import aware_timestamp
from app.market_data.models import Candle
from app.market_data.quality import audit_candles
from app.risk.risk_manager import RiskDecision
from app.strategies.base import Strategy
from backtesting.engine import ReplayResult
from backtesting.execution import BacktestExecution
from backtesting.history import CandleHistory
from backtesting.metrics import calculate_performance

GAP_REJECTION = "No observed trades in following interval; entry signal expired."


@dataclass(frozen=True)
class VerifiedEmptyInterval:
    start: datetime
    end: datetime
    first_observation_at: datetime
    evidence_sha256: str

    def __post_init__(self):
        for stamp in (self.start, self.end, self.first_observation_at):
            aware_timestamp(stamp)
        if self.start >= self.end or self.first_observation_at < self.end:
            raise ValueError("Invalid empty interval")
        if len(self.evidence_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.evidence_sha256):
            raise ValueError("Evidence digest required")


def validate_observed_history(candles: Sequence[Candle], gaps: Sequence[VerifiedEmptyInterval]) -> None:
    if not candles:
        raise ValueError("Observed candles required")
    first, last = candles[0], candles[-1]
    quality = audit_candles(candles, first.symbol, first.timeframe, first.timestamp, last.closed_at)
    expected = {(datetime.fromisoformat(g["start"]), datetime.fromisoformat(g["end_exclusive"])) for g in quality.gaps}
    actual = {(g.start, g.end) for g in gaps}
    if quality.errors or actual != expected or len(actual) != len(gaps):
        raise ValueError("Only exactly declared, verified empty intervals are allowed")
    by_time = {c.timestamp: c for c in candles}
    for gap in gaps:
        next_bar = by_time.get(gap.end)
        if next_bar is None or not gap.end <= gap.first_observation_at < next_bar.closed_at:
            raise ValueError("First post-gap trade must lie in the following observed candle")


class ObservedHistoryBacktester:
    """No fabricated bars, executions or marks inside an evidenced empty interval.

    Indicators restart after the gap. An existing position and all account risk
    state survive; protective exits use the next observed price, at its known time.
    Ordinary candles retain the existing conservative OHLC execution conventions.
    """

    def __init__(self, strategy: Strategy, execution: BacktestExecution):
        self.strategy, self.execution = strategy, execution

    def run(self, candles: Sequence[Candle], gaps: Sequence[VerifiedEmptyInterval] = ()) -> ReplayResult:
        validate_observed_history(candles, gaps)
        observed = tuple(candles)
        by_end = {g.end: g for g in gaps}
        pending, segment_start, segment = None, 0, observed
        for index, candle in enumerate(observed):
            gap = by_end.get(candle.timestamp)
            if gap is not None:
                if pending is not None:
                    self.execution.repository.record_signal(self.execution.session_id, pending, RiskDecision(False, (GAP_REJECTION,)))
                pending, segment_start = None, index
                segment = observed[index:]
            self.execution.on_bar(candle, pending, observed_open_at=gap.first_observation_at if gap else None)
            history = CandleHistory(segment, index - segment_start + 1)
            pending = self.strategy.analyze(history)
            if pending.symbol != candle.symbol or pending.timestamp != candle.closed_at:
                raise ValueError("Signal must match the observed candle")
        self.execution.record_unexecuted(pending)
        self.execution.finish(observed[-1])
        broker = self.execution.broker
        performance = calculate_performance(broker.settings.initial_capital, broker.snapshot().cash,
                                             broker.trades, self.execution.equity_curve, broker.total_fees)
        return ReplayResult(len(observed), len(observed), performance)
