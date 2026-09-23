"""Extension point for ATR/swing/trailing stops and partial exits."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.market_data.models import Candle
from app.portfolio.models import Position
from app.domain import positive_decimal


@dataclass(frozen=True)
class ExitPlan:
    stop_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    close_fraction: Decimal = Decimal("0")
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("stop_price", "take_profit_price"):
            if getattr(self, name) is not None:
                positive_decimal(getattr(self, name), name)
        positive_decimal(self.close_fraction, "close_fraction", allow_zero=True)
        if self.close_fraction > 1:
            raise ValueError("close_fraction cannot exceed 1")
        if (self.stop_price is not None or self.take_profit_price is not None or self.close_fraction > 0) and not self.reasons:
            raise ValueError("Exit proposals must include reasons")


class ExitPolicy(ABC):
    @abstractmethod
    def evaluate(self, position: Position, history: Sequence[Candle]) -> ExitPlan:
        """Propose exits; execution remains the broker's responsibility."""
