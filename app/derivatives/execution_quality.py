"""Fail-closed pre-trade execution-quality checks for future PAPER sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.domain import Direction, aware_timestamp, positive_decimal


@dataclass(frozen=True)
class ExecutionQuote:
    bid: Decimal
    ask: Decimal
    observed_at: datetime
    adverse_slippage_bps: Decimal

    def __post_init__(self) -> None:
        positive_decimal(self.bid, "bid")
        positive_decimal(self.ask, "ask")
        positive_decimal(self.adverse_slippage_bps, "adverse_slippage_bps", allow_zero=True)
        aware_timestamp(self.observed_at)
        if self.bid >= self.ask:
            raise ValueError("Execution quote requires bid below ask")

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread_bps(self) -> Decimal:
        return (self.ask - self.bid) / self.mid * Decimal("10000")


@dataclass(frozen=True)
class ExecutionQualityPolicy:
    maximum_age: timedelta = timedelta(seconds=20)
    maximum_spread_bps: Decimal = Decimal("5")
    maximum_mid_deviation_bps: Decimal = Decimal("10")
    maximum_cost_to_stop_fraction: Decimal = Decimal("0.25")

    def __post_init__(self) -> None:
        if not isinstance(self.maximum_age, timedelta) or self.maximum_age <= timedelta(0):
            raise ValueError("maximum_age must be positive")
        for name in (
            "maximum_spread_bps", "maximum_mid_deviation_bps",
            "maximum_cost_to_stop_fraction",
        ):
            positive_decimal(getattr(self, name), name)
        if self.maximum_cost_to_stop_fraction >= 1:
            raise ValueError("Execution costs must remain below the stop distance")


@dataclass(frozen=True)
class ExecutionQualityDecision:
    allowed: bool
    reasons: tuple[str, ...]
    spread_bps: Decimal
    mid_deviation_bps: Decimal
    estimated_cost_to_stop_fraction: Decimal
    estimated_entry_fill: Decimal
    estimated_stop_fill: Decimal


class ExecutionQualityGate:
    """Reject a trade when observable friction consumes too much planned risk."""

    def __init__(self, policy: ExecutionQualityPolicy | None = None) -> None:
        self.policy = policy or ExecutionQualityPolicy()

    def evaluate(self, direction: Direction, planned_entry: Decimal, stop_price: Decimal,
                 quote: ExecutionQuote, fee_rate: Decimal, now: datetime) -> ExecutionQualityDecision:
        if direction not in (Direction.LONG, Direction.SHORT):
            raise ValueError("Execution quality requires LONG or SHORT")
        positive_decimal(planned_entry, "planned_entry")
        positive_decimal(stop_price, "stop_price")
        positive_decimal(fee_rate, "fee_rate", allow_zero=True)
        aware_timestamp(now)
        if fee_rate >= 1:
            raise ValueError("fee_rate must be below one")
        if ((direction == Direction.LONG and stop_price >= planned_entry)
                or (direction == Direction.SHORT and stop_price <= planned_entry)):
            raise ValueError("Stop must be on the losing side of the planned entry")

        slippage = quote.adverse_slippage_bps / Decimal("10000")
        if direction == Direction.LONG:
            entry_fill = quote.ask * (Decimal("1") + slippage)
            stop_fill = stop_price * (Decimal("1") - slippage)
        else:
            entry_fill = quote.bid * (Decimal("1") - slippage)
            stop_fill = stop_price * (Decimal("1") + slippage)
        stop_distance = abs(planned_entry - stop_price)
        friction = (
            abs(entry_fill - planned_entry) + abs(stop_fill - stop_price)
            + entry_fill * fee_rate + stop_fill * fee_rate
        )
        cost_share = friction / stop_distance
        deviation = abs(quote.mid - planned_entry) / planned_entry * Decimal("10000")
        age = now - quote.observed_at
        failures = []
        if age < timedelta(0) or age > self.policy.maximum_age:
            failures.append("Quote is stale or timestamped in the future.")
        if quote.spread_bps > self.policy.maximum_spread_bps:
            failures.append("Observed spread exceeds the execution-quality cap.")
        if deviation > self.policy.maximum_mid_deviation_bps:
            failures.append("Quote moved too far from the planned entry.")
        if cost_share > self.policy.maximum_cost_to_stop_fraction:
            failures.append("Estimated fees, spread and slippage consume too much stop risk.")
        return ExecutionQualityDecision(
            not failures,
            tuple(failures) or ("Quote age, spread, deviation and cost burden are acceptable.",),
            quote.spread_bps, deviation, cost_share, entry_fill, stop_fill,
        )
