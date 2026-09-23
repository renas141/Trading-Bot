"""Exchange-neutral position and completed trade records."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain import Direction, aware_timestamp, positive_decimal, validate_symbol


@dataclass(frozen=True)
class Position:
    id: str
    symbol: str
    direction: Direction
    quantity: Decimal
    entry_price: Decimal
    opened_at: datetime
    entry_fee: Decimal
    leverage: Decimal = Decimal("1")
    stop_price: Decimal | None = None
    take_profit_price: Decimal | None = None

    def __post_init__(self) -> None:
        validate_symbol(self.symbol)
        aware_timestamp(self.opened_at)
        if not self.id or not isinstance(self.direction, Direction) or self.direction not in (Direction.LONG, Direction.SHORT):
            raise ValueError("Position requires an id and LONG/SHORT direction")
        for name in ("quantity", "entry_price", "leverage"):
            positive_decimal(getattr(self, name), name)
        if not 1 <= self.leverage <= 10:
            raise ValueError("Leverage must be between 1 and 10")
        positive_decimal(self.entry_fee, "entry_fee", allow_zero=True)
        for name in ("stop_price", "take_profit_price"):
            if getattr(self, name) is not None:
                positive_decimal(getattr(self, name), name)


@dataclass(frozen=True)
class Trade:
    id: str
    position: Position
    exit_price: Decimal
    closed_at: datetime
    exit_fee: Decimal
    exit_reason: str

    def __post_init__(self) -> None:
        aware_timestamp(self.closed_at)
        positive_decimal(self.exit_price, "exit_price")
        positive_decimal(self.exit_fee, "exit_fee", allow_zero=True)
        if self.closed_at < self.position.opened_at:
            raise ValueError("Exit cannot precede entry")
        if not self.id or not self.exit_reason.strip():
            raise ValueError("Trade id and exit reason are required")

    @property
    def fees(self) -> Decimal:
        return self.position.entry_fee + self.exit_fee

    @property
    def net_pnl(self) -> Decimal:
        sign = Decimal("1") if self.position.direction == Direction.LONG else Decimal("-1")
        return (self.exit_price - self.position.entry_price) * self.position.quantity * sign - self.fees


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: Decimal
    positions: tuple[Position, ...]
    realized_pnl: Decimal
