"""Validated OHLCV candles; timestamp denotes candle OPEN time."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.domain import aware_timestamp, positive_decimal, validate_symbol

TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        validate_symbol(self.symbol)
        aware_timestamp(self.timestamp)
        if self.timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported timeframe")
        for name in ("open", "high", "low", "close"):
            positive_decimal(getattr(self, name), name)
        positive_decimal(self.volume, "volume", allow_zero=True)
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Inconsistent OHLC prices")

    @property
    def closed_at(self) -> datetime:
        return self.timestamp + timedelta(seconds=TIMEFRAMES[self.timeframe])
