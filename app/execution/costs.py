"""Shared conservative simulation assumptions, not exchange contract specifications."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from app.config.settings import Settings
from app.domain import positive_decimal


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def ceil_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


@dataclass(frozen=True)
class ExecutionCosts:
    settings: Settings

    @property
    def adverse_fraction(self) -> Decimal:
        return (self.settings.paper_slippage_bps + self.settings.paper_spread_bps / 2) / Decimal("10000")

    def buy(self, reference: Decimal) -> Decimal:
        positive_decimal(reference, "reference_price")
        return ceil_step(reference * (1 + self.adverse_fraction), self.settings.price_tick)

    def sell(self, reference: Decimal) -> Decimal:
        positive_decimal(reference, "reference_price")
        fill = floor_step(reference * (1 - self.adverse_fraction), self.settings.price_tick)
        positive_decimal(fill, "sell_fill")
        return fill

    def entry_cost(self, reference: Decimal) -> Decimal:
        return self.buy(reference) * (1 + self.settings.paper_fee_rate)

    def exit_value(self, reference: Decimal) -> Decimal:
        return self.sell(reference) * (1 - self.settings.paper_fee_rate)
