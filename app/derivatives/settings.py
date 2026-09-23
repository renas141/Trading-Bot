"""Conservative, simulation-only perpetual settings."""

from dataclasses import dataclass, field
from decimal import Decimal

from app.derivatives.models import PerpetualContract
from app.domain import positive_decimal


@dataclass(frozen=True)
class DerivativeSettings:
    contract: PerpetualContract = field(default_factory=PerpetualContract)
    initial_capital: Decimal = Decimal("1000")
    max_leverage: int = 10
    max_risk_per_trade: Decimal = Decimal("0.01")
    max_total_risk: Decimal = Decimal("0.03")
    max_daily_loss: Decimal = Decimal("0.03")
    max_drawdown: Decimal = Decimal("0.10")
    max_margin_fraction: Decimal = Decimal("0.25")
    min_liquidation_buffer: Decimal = Decimal("0.02")
    max_position_notional: Decimal = Decimal("10000")
    fee_rate: Decimal = Decimal("0.0005")
    slippage_bps: Decimal = Decimal("5")
    min_order_notional: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        positive_decimal(self.initial_capital, "initial_capital")
        if type(self.max_leverage) is not int or not 1 <= self.max_leverage <= 10:
            raise ValueError("max_leverage must be an integer from 1 to 10")
        if self.max_leverage > self.contract.maximum_leverage:
            raise ValueError("max_leverage exceeds the contract initial-margin schedule")
        for name in ("max_risk_per_trade", "max_total_risk", "max_daily_loss",
                     "max_drawdown", "max_margin_fraction", "min_liquidation_buffer"):
            positive_decimal(getattr(self, name), name)
            if getattr(self, name) > 1:
                raise ValueError(f"{name} must be <= 1")
        if self.max_risk_per_trade > self.max_total_risk:
            raise ValueError("Per-trade risk cannot exceed total risk")
        for name in ("max_position_notional", "min_order_notional"):
            positive_decimal(getattr(self, name), name)
        for name in ("fee_rate", "slippage_bps"):
            positive_decimal(getattr(self, name), name, allow_zero=True)
        if self.fee_rate >= 1 or self.slippage_bps >= 10000:
            raise ValueError("Simulation costs must remain below 100%")
