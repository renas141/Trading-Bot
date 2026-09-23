"""Next-bar cash-funded execution with conservative OHLC stop/target handling."""

from decimal import Decimal
from datetime import datetime, timedelta

from app.database.repository import Repository
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import PaperBroker
from app.market_data.models import Candle
from app.risk.risk_manager import RiskDecision
from app.strategies.models import Signal


class BacktestExecution:
    def __init__(self, manager: OrderManager, broker: PaperBroker,
                 repository: Repository, session_id: str) -> None:
        if manager.broker is not broker:
            raise ValueError("Backtest execution must use the manager's broker")
        self.manager = manager
        self.broker = broker
        self.repository = repository
        self.session_id = session_id
        self.equity_curve: list[Decimal] = [broker.settings.initial_capital]
        self._finished = False

    def active_stop(self, position):
        """Stop active before this bar; extensions must not use this bar's future prices."""
        return position.stop_price

    def _exit(self, position_id: str, price: Decimal, timestamp: datetime, reason: str) -> None:
        self.broker.close_position(position_id, price, timestamp, reason)
        equity = self.broker.risk_state.last_equity
        self.equity_curve.append(equity)
        self.repository.record_equity(self.session_id, timestamp, equity)

    def _record_equity(self, candle: Candle, *, at_open: bool = False, observed_open_at: datetime | None = None) -> None:
        price = candle.open if at_open else candle.close
        # A candle covers [open, close). Its P&L belongs to the day before a
        # midnight closing boundary, not to the following candle's UTC day.
        timestamp = (observed_open_at or candle.timestamp) if at_open else candle.closed_at - timedelta(microseconds=1)
        context = self.broker.mark(price, timestamp)
        self.equity_curve.append(context.equity)
        self.repository.record_equity(self.session_id, timestamp, context.equity)

    def on_bar(self, candle: Candle, pending: Signal | None, *, observed_open_at: datetime | None = None) -> None:
        if self._finished:
            raise ValueError("A finished execution session cannot be reused")
        open_at = observed_open_at or candle.timestamp
        if not candle.timestamp <= open_at < candle.closed_at:
            raise ValueError("Observed first trade must lie inside its candle")
        self._record_equity(candle, at_open=True, observed_open_at=open_at)
        # Existing gap exits happen before evaluating a new entry at this open.
        for position in self.broker.snapshot().positions:
            stop = self.active_stop(position)
            if stop is not None and candle.open <= stop:
                self._exit(position.id, candle.open, open_at, "STOP_GAP")
            elif position.take_profit_price is not None and candle.open >= position.take_profit_price:
                # No favorable gap improvement assumed for the target exit.
                self._exit(position.id, position.take_profit_price, open_at, "TAKE_PROFIT_GAP")
        if pending is not None:
            if pending.timestamp > open_at:
                raise ValueError("Cannot execute a signal before it is observed")
            self.manager.submit(pending, candle.open, open_at)
        # Mark fees and adverse entry costs before any intrabar exit.
        self._record_equity(candle, at_open=True, observed_open_at=open_at)
        for position in self.broker.snapshot().positions:
            stop = self.active_stop(position)
            stop_hit = stop is not None and candle.low <= stop
            target_hit = position.take_profit_price is not None and candle.high >= position.take_profit_price
            if stop_hit:
                reason = "STOP_FIRST_AMBIGUOUS_BAR" if target_hit else "STOP_LOSS"
                self._exit(position.id, stop, candle.closed_at - timedelta(microseconds=1), reason)
            elif target_hit:
                self._exit(position.id, position.take_profit_price, candle.closed_at - timedelta(microseconds=1), "TAKE_PROFIT")
        self._record_equity(candle)

    def record_unexecuted(self, signal: Signal) -> None:
        self.repository.record_signal(self.session_id, signal,
                                      RiskDecision(False, ("No following candle available; signal not executed.",)))

    def finish(self, candle: Candle) -> None:
        if self._finished:
            raise ValueError("A finished execution session cannot be reused")
        for position in self.broker.snapshot().positions:
            self._exit(position.id, candle.close, candle.closed_at - timedelta(microseconds=1), "END_OF_DATA")
        self._record_equity(candle)
        self._finished = True
