"""Central risk contracts; default denial remains available for idle paper mode."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from app.config.settings import RiskLimits
from app.domain import positive_decimal
from app.portfolio.models import PortfolioSnapshot
from app.strategies.models import Signal
from app.risk.state import RiskContext


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reasons: tuple[str, ...]
    quantity: Decimal = Decimal("0")
    leverage: Decimal = Decimal("1")
    stop_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    estimated_loss: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool or not isinstance(self.reasons, tuple) or not self.reasons or not all(self.reasons):
            raise ValueError("Risk decisions require a boolean and reasons")
        positive_decimal(self.quantity, "quantity", allow_zero=not self.allowed)
        positive_decimal(self.leverage, "leverage")
        if not 1 <= self.leverage <= 10:
            raise ValueError("Leverage cannot exceed the hard cap of 10")
        if not self.allowed and self.quantity != 0:
            raise ValueError("Rejected decisions must have zero quantity")
        for name in ("stop_price", "take_profit_price"):
            if getattr(self, name) is not None:
                positive_decimal(getattr(self, name), name)
        positive_decimal(self.estimated_loss, "estimated_loss", allow_zero=True)


class RiskManager(ABC):
    @abstractmethod
    def evaluate(self, signal: Signal, portfolio: PortfolioSnapshot,
                 context: RiskContext | None = None) -> RiskDecision:
        """Approve or deny; future implementations must enforce all configured limits."""


class RejectAllRiskManager(RiskManager):
    """Safe default until sizing, stops and portfolio limits are implemented."""

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def evaluate(self, signal: Signal, portfolio: PortfolioSnapshot,
                 context: RiskContext | None = None) -> RiskDecision:
        reason = "Kill switch is active." if self.limits.kill_switch else "Trading is disabled by the deny-all policy."
        return RiskDecision(False, (reason,))
