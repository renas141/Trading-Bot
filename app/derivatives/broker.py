"""In-memory accounting for BACKTEST/PAPER perpetual positions; no exchange I/O."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.derivatives.models import (
    DerivativeAccountSnapshot,
    DerivativePosition,
    DerivativeTrade,
)
from app.derivatives.risk import DerivativeRiskDecision, ceil_step, floor_step
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction, aware_timestamp, positive_decimal
from app.strategies.models import Signal


class DerivativePaperBroker:
    """Single-position linear-perpetual ledger with settled funding."""

    def __init__(self, settings: DerivativeSettings) -> None:
        self.settings = settings
        self._balance = settings.initial_capital
        self._position: DerivativePosition | None = None
        self._funding_paid = Decimal("0")
        self._last_mark: Decimal | None = None
        self.trades: list[DerivativeTrade] = []

    def snapshot(self, mark_price: Decimal | None = None) -> DerivativeAccountSnapshot:
        mark = mark_price or self._last_mark
        unrealized = Decimal("0")
        reserved = Decimal("0")
        if self._position is not None:
            if mark is None:
                mark = self._position.entry_price
            unrealized = self._position.unrealized_pnl(mark)
            reserved = self._position.initial_margin
        equity = self._balance + unrealized
        return DerivativeAccountSnapshot(
            self._balance, equity, self._balance - reserved, self._position,
            self._balance - self.settings.initial_capital,
        )

    def mark(self, mark_price: Decimal) -> DerivativeAccountSnapshot:
        positive_decimal(mark_price, "mark_price")
        self._last_mark = mark_price
        return self.snapshot(mark_price)

    def open_position(self, signal: Signal, decision: DerivativeRiskDecision,
                      timestamp: datetime) -> DerivativePosition:
        aware_timestamp(timestamp)
        if not decision.allowed or decision.entry_price is None or decision.stop_price is None:
            raise ValueError("A complete allowed risk decision is required")
        if self._position is not None or signal.direction not in (Direction.LONG, Direction.SHORT):
            raise ValueError("Cannot open this derivative position")
        contract = self.settings.contract
        expected_margin = decision.quantity * decision.entry_price / decision.leverage
        if (decision.initial_margin != expected_margin or decision.liquidation_price is None
                or decision.leverage > min(10, self.settings.max_leverage, contract.maximum_leverage)):
            raise ValueError("Risk decision margin or leverage is inconsistent")
        entry_fee = decision.quantity * decision.entry_price * self.settings.fee_rate
        if expected_margin + entry_fee > self._balance:
            raise ValueError("Insufficient balance")
        position = DerivativePosition(
            uuid4().hex, contract, signal.direction, decision.quantity,
            decision.entry_price, decision.leverage, timestamp, entry_fee,
            expected_margin, decision.liquidation_price, decision.stop_price,
            decision.take_profit_price,
        )
        self._balance -= entry_fee
        self._position = position
        self._funding_paid = Decimal("0")
        self._last_mark = position.entry_price
        return position

    def apply_funding(self, rate: Decimal, mark_price: Decimal) -> Decimal:
        """Positive rates are paid by longs and received by shorts."""
        if not isinstance(rate, Decimal) or not rate.is_finite():
            raise ValueError("Funding rate must be a finite Decimal")
        positive_decimal(mark_price, "mark_price")
        if self._position is None:
            return Decimal("0")
        sign = Decimal("1") if self._position.direction == Direction.LONG else Decimal("-1")
        payment = self._position.quantity * mark_price * rate * sign
        self._balance -= payment
        self._funding_paid += payment
        self._last_mark = mark_price
        return payment

    def tighten_stop(self, new_stop: Decimal) -> DerivativePosition:
        """Apply a close-derived stop for future bars only; never loosen it."""
        position = self._position
        if position is None:
            raise ValueError("No derivative position")
        positive_decimal(new_stop, "new_stop")
        if position.direction == Direction.LONG and new_stop <= position.stop_price:
            raise ValueError("LONG stop must tighten upward")
        if position.direction == Direction.SHORT and new_stop >= position.stop_price:
            raise ValueError("SHORT stop must tighten downward")
        self._position = replace(position, stop_price=new_stop)
        return self._position

    def _exit_fill(self, reference: Decimal) -> Decimal:
        position = self._position
        if position is None:
            raise ValueError("No derivative position")
        positive_decimal(reference, "reference_price")
        fraction = self.settings.adverse_execution_bps / Decimal("10000")
        step = self.settings.contract.tick_size
        if position.direction == Direction.LONG:
            return floor_step(reference * (1 - fraction), step)
        return ceil_step(reference * (1 + fraction), step)

    def close_position(self, reference_price: Decimal, timestamp: datetime,
                       reason: str, *, liquidation: bool = False) -> DerivativeTrade:
        aware_timestamp(timestamp)
        position = self._position
        if position is None:
            raise ValueError("No derivative position")
        exit_price = self._exit_fill(reference_price)
        exit_fee = position.quantity * exit_price * self.settings.fee_rate
        liquidation_fee = (position.quantity * exit_price * self.settings.contract.liquidation_fee_rate
                           if liquidation else Decimal("0"))
        trade = DerivativeTrade(
            uuid4().hex, position, exit_price, timestamp, exit_fee,
            self._funding_paid, liquidation_fee, reason,
        )
        self._balance += trade.price_pnl - exit_fee - liquidation_fee
        self._position = None
        self._funding_paid = Decimal("0")
        self._last_mark = exit_price
        self.trades.append(trade)
        return trade

    @property
    def total_fees(self) -> Decimal:
        return sum((trade.fees for trade in self.trades), Decimal("0"))

    @property
    def total_funding_paid(self) -> Decimal:
        return sum((trade.funding_paid for trade in self.trades), Decimal("0"))
