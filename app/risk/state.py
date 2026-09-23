"""Observed equity limits for a single simulation session, using UTC days."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from app.config.settings import RiskLimits
from app.domain import aware_timestamp, positive_decimal


@dataclass(frozen=True)
class RiskContext:
    price: Decimal
    timestamp: datetime
    equity: Decimal
    peak_equity: Decimal
    day_start_equity: Decimal
    daily_halted: bool
    drawdown_halted: bool
    kill_switch: bool


class RiskState:
    """Daily loss latches until a new UTC day; drawdown latches for the session."""

    def __init__(self, capital: Decimal, limits: RiskLimits) -> None:
        self.limits = limits
        self.last_equity = self.peak = self.day_start = capital
        self.day: date | None = None
        self.last_timestamp: datetime | None = None
        self.daily_halted = self.drawdown_halted = False
        self.kill_switch = limits.kill_switch

    def observe(self, price: Decimal, timestamp: datetime, equity: Decimal) -> RiskContext:
        aware_timestamp(timestamp)
        positive_decimal(price, "price")
        positive_decimal(equity, "equity", allow_zero=True)
        if self.last_timestamp is not None and timestamp < self.last_timestamp:
            raise ValueError("Risk observations must be chronological")
        day = timestamp.astimezone(timezone.utc).date()
        if day != self.day:
            # Opening gaps belong to the new day's P&L, measured from the prior mark.
            self.day_start = self.last_equity
            self.daily_halted = False
            self.day = day
        self.peak = max(self.peak, equity)
        self.daily_halted |= equity <= self.day_start * (1 - self.limits.max_daily_loss)
        self.drawdown_halted |= equity <= self.peak * (1 - self.limits.max_drawdown)
        self.last_equity, self.last_timestamp = equity, timestamp
        return RiskContext(price, timestamp, equity, self.peak, self.day_start,
                           self.daily_halted, self.drawdown_halted, self.kill_switch)
