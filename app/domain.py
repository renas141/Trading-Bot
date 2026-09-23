"""Shared value types. No exchange-specific dependencies."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class TradingMode(StrEnum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    FILLED = "FILLED"


def positive_decimal(value: Decimal, name: str, *, allow_zero: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{name} must be {'non-negative' if allow_zero else 'positive'}")


def aware_timestamp(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware")


def validate_symbol(symbol: str) -> None:
    parts = symbol.split("/")
    if len(parts) != 2 or not all(part.isalnum() and part.isupper() for part in parts):
        raise ValueError("Use an explicit BASE/QUOTE symbol, e.g. BTC/EUR")
