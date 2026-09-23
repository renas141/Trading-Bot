"""Value objects for a linear USD-margined perpetual simulation."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain import Direction, aware_timestamp, positive_decimal, validate_symbol


@dataclass(frozen=True)
class PerpetualContract:
    """Explicit contract assumptions; these are not account eligibility claims."""

    market_id: str = "PF_XBTUSD"
    symbol: str = "BTC/USD"
    tick_size: Decimal = Decimal("1")
    quantity_step: Decimal = Decimal("0.0001")
    initial_margin_rate: Decimal = Decimal("0.10")
    maintenance_margin_rate: Decimal = Decimal("0.05")
    liquidation_fee_rate: Decimal = Decimal("0.0025")

    def __post_init__(self) -> None:
        validate_symbol(self.symbol)
        if not self.market_id.strip():
            raise ValueError("market_id is required")
        for name in ("tick_size", "quantity_step", "initial_margin_rate",
                     "maintenance_margin_rate", "liquidation_fee_rate"):
            positive_decimal(getattr(self, name), name,
                             allow_zero=name == "liquidation_fee_rate")
        if self.initial_margin_rate > 1 or self.maintenance_margin_rate >= self.initial_margin_rate:
            raise ValueError("Margin rates must satisfy 0 < maintenance < initial <= 1")
        if self.liquidation_fee_rate >= 1:
            raise ValueError("liquidation_fee_rate must be below one")

    @property
    def maximum_leverage(self) -> int:
        return int(Decimal("1") / self.initial_margin_rate)

    def liquidation_price(self, entry_price: Decimal, leverage: int,
                          direction: Direction) -> Decimal:
        """Bankruptcy threshold from equity == maintenance margin for a linear contract."""
        positive_decimal(entry_price, "entry_price")
        if type(leverage) is not int or not 1 <= leverage <= self.maximum_leverage:
            raise ValueError("leverage exceeds the contract margin schedule")
        if direction == Direction.LONG:
            return entry_price * (1 - Decimal("1") / leverage) / (1 - self.maintenance_margin_rate)
        if direction == Direction.SHORT:
            return entry_price * (1 + Decimal("1") / leverage) / (1 + self.maintenance_margin_rate)
        raise ValueError("Liquidation price requires LONG or SHORT")


@dataclass(frozen=True)
class DerivativePosition:
    id: str
    contract: PerpetualContract
    direction: Direction
    quantity: Decimal
    entry_price: Decimal
    leverage: int
    opened_at: datetime
    entry_fee: Decimal
    initial_margin: Decimal
    liquidation_price: Decimal
    stop_price: Decimal
    take_profit_price: Decimal | None = None

    def __post_init__(self) -> None:
        aware_timestamp(self.opened_at)
        if not self.id or self.direction not in (Direction.LONG, Direction.SHORT):
            raise ValueError("A derivative position needs an id and LONG/SHORT direction")
        for name in ("quantity", "entry_price", "entry_fee", "initial_margin",
                     "liquidation_price", "stop_price"):
            positive_decimal(getattr(self, name), name,
                             allow_zero=name in ("entry_fee", "liquidation_price"))
        if type(self.leverage) is not int or not 1 <= self.leverage <= min(10, self.contract.maximum_leverage):
            raise ValueError("Position leverage must be an integer from 1 to the 10x hard cap")
        if self.take_profit_price is not None:
            positive_decimal(self.take_profit_price, "take_profit_price")
        if self.direction == Direction.LONG:
            if not self.liquidation_price < self.stop_price:
                raise ValueError("LONG requires liquidation below its active stop")
            if self.take_profit_price is not None and self.take_profit_price <= self.entry_price:
                raise ValueError("LONG target must be above entry")
        else:
            if not self.stop_price < self.liquidation_price:
                raise ValueError("SHORT requires its active stop below liquidation")
            if self.take_profit_price is not None and self.take_profit_price >= self.entry_price:
                raise ValueError("SHORT target must be below entry")

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.entry_price

    def unrealized_pnl(self, mark_price: Decimal) -> Decimal:
        positive_decimal(mark_price, "mark_price")
        sign = Decimal("1") if self.direction == Direction.LONG else Decimal("-1")
        return (mark_price - self.entry_price) * self.quantity * sign


@dataclass(frozen=True)
class DerivativeTrade:
    id: str
    position: DerivativePosition
    exit_price: Decimal
    closed_at: datetime
    exit_fee: Decimal
    funding_paid: Decimal
    liquidation_fee: Decimal
    exit_reason: str

    def __post_init__(self) -> None:
        aware_timestamp(self.closed_at)
        positive_decimal(self.exit_price, "exit_price")
        positive_decimal(self.exit_fee, "exit_fee", allow_zero=True)
        positive_decimal(self.liquidation_fee, "liquidation_fee", allow_zero=True)
        if not isinstance(self.funding_paid, Decimal) or not self.funding_paid.is_finite():
            raise ValueError("funding_paid must be a finite Decimal")
        if self.closed_at < self.position.opened_at or not self.id or not self.exit_reason.strip():
            raise ValueError("Invalid derivative trade close")

    @property
    def price_pnl(self) -> Decimal:
        return self.position.unrealized_pnl(self.exit_price)

    @property
    def fees(self) -> Decimal:
        return self.position.entry_fee + self.exit_fee + self.liquidation_fee

    @property
    def net_pnl(self) -> Decimal:
        return self.price_pnl - self.fees - self.funding_paid


@dataclass(frozen=True)
class DerivativeAccountSnapshot:
    balance: Decimal
    equity: Decimal
    available_collateral: Decimal
    position: DerivativePosition | None
    realized_pnl: Decimal
