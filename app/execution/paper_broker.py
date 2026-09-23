"""Small cash-funded LONG simulation. No networking or leveraged execution."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.config.settings import Settings
from app.database.repository import Repository
from app.domain import Direction, OrderSide, TradingMode, positive_decimal
from app.errors import LiveTradingDisabled, SimulationError
from app.execution.base import Broker
from app.execution.models import Order
from app.execution.costs import ExecutionCosts, floor_step
from app.portfolio.models import PortfolioSnapshot, Position, Trade
from app.risk.risk_manager import RiskDecision
from app.risk.state import RiskContext, RiskState
from app.risk.stop_risk import StopRiskManager
from app.strategies.models import Signal


class PaperBroker(Broker):
    """Low-level simulator; application entries must go through OrderManager.

    Every submitted approval is independently checked against the central stop-risk
    policy using current portfolio state. Strategies never control position size.
    """

    def __init__(self, settings: Settings, repository: Repository, session_id: str) -> None:
        if settings.mode not in (TradingMode.PAPER, TradingMode.BACKTEST):
            raise LiveTradingDisabled("PaperBroker only accepts simulation modes")
        sessions = repository.records("sessions", session_id)
        if (len(sessions) != 1 or sessions[0]["status"] != "RUNNING"
                or sessions[0]["mode"] != settings.mode.value
                or sessions[0]["symbol"] != settings.symbol
                or Decimal(sessions[0]["initial_capital"]) != settings.initial_capital):
            raise SimulationError("Broker requires a matching running session")
        if repository.records("positions", session_id):
            raise SimulationError("Resuming an existing portfolio is not implemented")
        self.settings = settings
        self.repository = repository
        self.session_id = session_id
        self._cash = settings.initial_capital
        self._positions: dict[str, Position] = {}
        self._realized_pnl = Decimal("0")
        self.costs = ExecutionCosts(settings)
        self.risk_state = RiskState(settings.initial_capital, settings.risk)
        self.risk_guard = StopRiskManager(settings)
        self.trades: list[Trade] = []
        self.total_fees = Decimal("0")

    def snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(self._cash, tuple(self._positions.values()), self._realized_pnl)

    def trip_kill_switch(self) -> None:
        """Block further entries in this session; protective exits remain possible."""
        self.risk_state.kill_switch = True

    def mark(self, price: Decimal, timestamp: datetime) -> RiskContext:
        equity = self._cash + sum((p.quantity * self.costs.exit_value(price)
                                  for p in self._positions.values()), Decimal("0"))
        return self.risk_state.observe(price, timestamp, equity)

    def open_position(self, signal: Signal, decision: RiskDecision, price: Decimal,
                      timestamp: datetime | None = None) -> Order:
        timestamp = timestamp or signal.timestamp
        if not decision.allowed or self.settings.risk.kill_switch:
            raise SimulationError("Entry denied by risk gate or kill switch")
        if signal.symbol != self.settings.symbol:
            raise SimulationError("Symbol does not match configured quote-currency account")
        if signal.direction != Direction.LONG or decision.leverage != 1:
            raise SimulationError("Only cash-funded LONG simulation at 1x is implemented")
        if len(self._positions) >= self.settings.risk.max_positions:
            raise SimulationError("Maximum number of positions reached")
        positive_decimal(price, "price")
        context = self.mark(price, timestamp)
        checked = self.risk_guard.evaluate(signal, self.snapshot(), context)
        if (not checked.allowed or decision.quantity > checked.quantity
                or decision.stop_price != checked.stop_price
                or decision.take_profit_price != checked.take_profit_price
                or floor_step(decision.quantity, self.settings.quantity_step) != decision.quantity):
            raise SimulationError("Entry approval does not satisfy the current central risk limits")
        fill = self.costs.buy(price)
        notional = fill * decision.quantity
        if decision.quantity < self.settings.min_order_quantity:
            raise SimulationError("Position is below the simulation minimum quantity")
        if notional < self.settings.min_order_notional:
            raise SimulationError("Position is below the simulation minimum notional")
        if notional > self.settings.risk.max_position_notional:
            raise SimulationError("Maximum position notional exceeded")
        fee = notional * self.settings.paper_fee_rate
        if notional + fee > self._cash:
            raise SimulationError("Insufficient virtual cash including fees")
        position = Position(str(uuid4()), signal.symbol, signal.direction, decision.quantity,
                            fill, timestamp, fee, stop_price=checked.stop_price,
                            take_profit_price=checked.take_profit_price)
        order = Order(str(uuid4()), position.id, signal.symbol, OrderSide.BUY, decision.quantity,
                      fill, fee, timestamp, signal.reasons + decision.reasons)
        self.repository.record_open(self.session_id, position, order)
        # Mutate memory only after persistence succeeds.
        self._cash -= notional + fee
        self._positions[position.id] = position
        self.total_fees += fee
        self.mark(price, timestamp)
        return order

    def close_position(self, position_id: str, price: Decimal, timestamp: datetime, reason: str) -> Trade:
        if position_id not in self._positions:
            raise SimulationError("Unknown or already closed position")
        positive_decimal(price, "price")
        position = self._positions[position_id]
        self.mark(price, timestamp)
        fill = self.costs.sell(price)
        fee = fill * position.quantity * self.settings.paper_fee_rate
        trade = Trade(str(uuid4()), position, fill, timestamp, fee, reason)
        order = Order(str(uuid4()), position.id, position.symbol, OrderSide.SELL, position.quantity,
                      fill, fee, timestamp, (reason,))
        self.repository.record_close(self.session_id, trade, order)
        self._cash += fill * position.quantity - fee
        self._realized_pnl += trade.net_pnl
        del self._positions[position_id]
        self.total_fees += fee
        self.trades.append(trade)
        self.mark(price, timestamp)
        return trade
