"""Explainable strategy output."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain import Direction, aware_timestamp, positive_decimal, validate_symbol


@dataclass(frozen=True)
class Signal:
    symbol: str
    timestamp: datetime
    direction: Direction
    confidence: Decimal
    reasons: tuple[str, ...]
    strategy: str
    strategy_version: str
    stop_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    requested_leverage: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        validate_symbol(self.symbol)
        aware_timestamp(self.timestamp)
        if not isinstance(self.direction, Direction):
            raise ValueError("direction must be a Direction")
        positive_decimal(self.confidence, "confidence", allow_zero=True)
        if self.confidence > 1:
            raise ValueError("confidence must be between 0 and 1")
        if not isinstance(self.reasons, tuple) or not self.reasons or not all(reason.strip() for reason in self.reasons):
            raise ValueError("Every signal must explain its decision")
        if not self.strategy.strip() or not self.strategy_version.strip():
            raise ValueError("Strategy name and version are required")
        for name in ("stop_price", "take_profit_price"):
            if getattr(self, name) is not None:
                positive_decimal(getattr(self, name), name)
        positive_decimal(self.requested_leverage, "requested_leverage")
