"""Order records. Only simulated filled market orders exist in this phase."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain import OrderSide, OrderStatus, aware_timestamp, positive_decimal, validate_symbol


@dataclass(frozen=True)
class Order:
    id: str
    position_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    fill_price: Decimal
    fee: Decimal
    timestamp: datetime
    reasons: tuple[str, ...]
    status: OrderStatus = OrderStatus.FILLED

    def __post_init__(self) -> None:
        validate_symbol(self.symbol)
        aware_timestamp(self.timestamp)
        for name in ("quantity", "fill_price"):
            positive_decimal(getattr(self, name), name)
        positive_decimal(self.fee, "fee", allow_zero=True)
        if not self.id or not self.position_id or not isinstance(self.reasons, tuple) or not self.reasons or not all(self.reasons):
            raise ValueError("Order requires identifiers and decision reasons")
        if not isinstance(self.side, OrderSide) or not isinstance(self.status, OrderStatus):
            raise ValueError("Invalid order side or status")
