"""Research-only close-based trailing stop, effective from the NEXT bar.

Original entry positions remain immutable. Every tighter stop is an append-only
exit-policy decision; trade.position.stop_price continues to mean INITIAL stop.
The policy is intentionally not wired into the running PAPER observer.
"""

from collections import deque
from dataclasses import replace
from decimal import Decimal

from app.domain import TradingMode
from app.execution.costs import floor_step
from app.indicators.core import average_true_range
from app.strategies.base import Strategy
from backtesting.candidate_research import make_candidate
from backtesting.execution import BacktestExecution


class SlowUncappedStrategy(Strategy):
    name, version = "slow_breakout_uncapped", "0.1.0"

    def __init__(self):
        self.base = make_candidate("slow_breakout")
        self.parameters = self.base.parameters

    def analyze(self, history):
        signal = self.base.analyze(history)
        return replace(signal, take_profit_price=None, strategy=self.name, strategy_version=self.version,
                       reasons=signal.reasons + ("No fixed profit target; close-based trailing exit policy.",))


class TrailingExecution(BacktestExecution):
    """Highest observed close since entry minus 3 * simple ATR(42), never loosened."""
    period = 42
    multiple = Decimal(3)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.broker.settings.mode != TradingMode.BACKTEST:
            raise ValueError("Trailing research is BACKTEST only")
        self.history = deque(maxlen=self.period + 1)
        self.stops, self.highest = {}, {}
        with self.repository.transaction():
            self.repository.connection.execute("""CREATE TABLE IF NOT EXISTS exit_updates (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                position_id TEXT NOT NULL REFERENCES positions(id), observed_close_at TEXT NOT NULL,
                effective_from TEXT NOT NULL, previous_stop TEXT NOT NULL, new_stop TEXT NOT NULL,
                highest_close TEXT NOT NULL, atr TEXT NOT NULL, reason TEXT NOT NULL
            )""")

    def active_stop(self, position):
        return self.stops.get(position.id, position.stop_price)

    def _exit(self, position_id, price, timestamp, reason):
        position = next(p for p in self.broker.snapshot().positions if p.id == position_id)
        if reason in {"STOP_GAP", "STOP_LOSS"} and self.stops.get(position_id, position.stop_price) > position.stop_price:
            reason = "TRAILING_STOP_GAP" if reason == "STOP_GAP" else "TRAILING_STOP"
        super()._exit(position_id, price, timestamp, reason)

    def on_bar(self, candle, pending, *, observed_open_at=None):
        if self.history and self.history[-1].closed_at != candle.timestamp:
            raise ValueError("Trailing study requires continuous source candles")
        super().on_bar(candle, pending, observed_open_at=observed_open_at)
        self.history.append(candle)
        positions = self.broker.snapshot().positions
        ids = {p.id for p in positions}
        self.stops = {key: value for key, value in self.stops.items() if key in ids}
        self.highest = {key: value for key, value in self.highest.items() if key in ids}
        for position in positions:
            self.highest[position.id] = max(self.highest.get(position.id, candle.close), candle.close)
        if len(self.history) < self.period + 1:
            return
        atr = average_true_range(tuple(self.history), self.period)
        if atr <= 0:
            return
        for position in positions:
            previous = self.active_stop(position)
            proposed = floor_step(self.highest[position.id] - self.multiple * atr, self.broker.settings.price_tick)
            if previous is None or proposed <= previous:
                continue
            # No check against this candle's low and no same-close fill. If the
            # next observed open is below the new stop it becomes a gap exit there.
            with self.repository.transaction():
                self.repository.connection.execute("""INSERT INTO exit_updates
                    (session_id,position_id,observed_close_at,effective_from,previous_stop,new_stop,highest_close,atr,reason)
                    VALUES (?,?,?,?,?,?,?,?,?)""", (self.session_id, position.id, candle.closed_at.isoformat(),
                    candle.closed_at.isoformat(), str(previous), str(proposed), str(self.highest[position.id]), str(atr),
                    "Highest closed price since entry minus 3 * simple ATR(42); effective next bar only."))
            self.stops[position.id] = proposed
