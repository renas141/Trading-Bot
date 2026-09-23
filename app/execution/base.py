"""Execution and broker contracts, without exchange order transport."""

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from app.execution.models import Order
from app.portfolio.models import PortfolioSnapshot, Trade
from app.risk.risk_manager import RiskDecision
from app.risk.state import RiskContext
from app.strategies.models import Signal


class Broker(ABC):
    @abstractmethod
    def mark(self, price: Decimal, timestamp: datetime) -> RiskContext:
        """Value the portfolio and update observed risk limits."""

    @abstractmethod
    def snapshot(self) -> PortfolioSnapshot:
        """Return an immutable view of the simulated portfolio."""

    @abstractmethod
    def open_position(self, signal: Signal, decision: RiskDecision, price: Decimal,
                      timestamp: datetime | None = None) -> Order:
        """Consume a risk decision; never connect to a live venue."""

    @abstractmethod
    def close_position(self, position_id: str, price: Decimal, timestamp: datetime, reason: str) -> Trade:
        """Close a simulated position with an explicit explanation."""


class Execution(ABC):
    @abstractmethod
    def submit(self, signal: Signal, price: Decimal, timestamp: datetime | None = None) -> RiskDecision:
        """Apply the central risk gate before invoking the broker."""
