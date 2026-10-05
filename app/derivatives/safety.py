"""Second-generation leverage safeguards for future research and PAPER sessions.

The existing forward protocol remains bound to its original risk and broker code.
This module is deliberately additive so a future protocol can test stronger
funding-aware margin and tail-loss controls without rewriting prior evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from app.derivatives.broker import DerivativePaperBroker
from app.derivatives.models import DerivativePosition
from app.derivatives.risk import (
    DerivativeRiskContext,
    DerivativeRiskDecision,
    LeveragedRiskManager,
    ceil_step,
    floor_step,
)
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction, positive_decimal
from app.strategies.models import Signal


@dataclass(frozen=True)
class MarginHealth:
    mark_price: Decimal
    allocated_equity: Decimal
    maintenance_margin: Decimal
    liquidation_fee_reserve: Decimal
    excess_margin: Decimal
    dynamic_liquidation_price: Decimal

    @property
    def liquidatable(self) -> bool:
        return self.excess_margin <= 0


def dynamic_liquidation_price(position: DerivativePosition,
                              funding_paid: Decimal = Decimal("0")) -> Decimal:
    """Return an isolated-margin threshold including funding and liquidation fee.

    Positive ``funding_paid`` means the position paid funding. Negative values are
    receipts and move the threshold away from the entry.
    """
    if not isinstance(funding_paid, Decimal) or not funding_paid.is_finite():
        raise ValueError("funding_paid must be a finite Decimal")
    quantity = position.quantity
    contract = position.contract
    maintenance_and_fee = (
        contract.maintenance_margin_rate + contract.liquidation_fee_rate
    )
    if position.direction == Direction.LONG:
        numerator = quantity * position.entry_price - position.initial_margin + funding_paid
        denominator = quantity * (Decimal("1") - maintenance_and_fee)
    else:
        numerator = position.initial_margin - funding_paid + quantity * position.entry_price
        denominator = quantity * (Decimal("1") + maintenance_and_fee)
    threshold = numerator / denominator
    return max(Decimal("0"), threshold)


def margin_health(position: DerivativePosition, mark_price: Decimal,
                  funding_paid: Decimal = Decimal("0")) -> MarginHealth:
    positive_decimal(mark_price, "mark_price")
    if not isinstance(funding_paid, Decimal) or not funding_paid.is_finite():
        raise ValueError("funding_paid must be a finite Decimal")
    notional = position.quantity * mark_price
    allocated = position.initial_margin + position.unrealized_pnl(mark_price) - funding_paid
    maintenance = notional * position.contract.maintenance_margin_rate
    liquidation_fee = notional * position.contract.liquidation_fee_rate
    return MarginHealth(
        mark_price,
        allocated,
        maintenance,
        liquidation_fee,
        allocated - maintenance - liquidation_fee,
        dynamic_liquidation_price(position, funding_paid),
    )


class FundingAwarePaperBroker(DerivativePaperBroker):
    """PAPER ledger exposing dynamic margin health after every funding payment."""

    def margin_health(self, mark_price: Decimal | None = None) -> MarginHealth | None:
        position = self._position
        if position is None:
            return None
        mark = mark_price or self._last_mark or position.entry_price
        return margin_health(position, mark, self._funding_paid)

    def liquidation_required(self, mark_price: Decimal | None = None) -> bool:
        health = self.margin_health(mark_price)
        return health is not None and health.liquidatable


@dataclass(frozen=True)
class StressRiskPolicy:
    """Fixed rules for accepting moderate and full-confirmation signals."""

    minimum_confidence: Decimal = Decimal("0.8333333333333333333333333333")
    full_confidence: Decimal = Decimal("1")
    partial_risk_fraction: Decimal = Decimal("0.005")
    full_risk_fraction: Decimal = Decimal("0.0125")
    tail_gap_fraction: Decimal = Decimal("0.02")
    maximum_tail_loss_fraction: Decimal = Decimal("0.03")
    funding_stress_per_bar: Decimal = Decimal("0.00002")
    maximum_holding_bars: int = 42
    minimum_free_collateral_fraction: Decimal = Decimal("0.05")

    def __post_init__(self) -> None:
        for name in (
            "minimum_confidence", "full_confidence", "partial_risk_fraction",
            "full_risk_fraction", "tail_gap_fraction", "maximum_tail_loss_fraction",
            "funding_stress_per_bar", "minimum_free_collateral_fraction",
        ):
            positive_decimal(getattr(self, name), name, allow_zero=name == "funding_stress_per_bar")
        if (self.minimum_confidence > self.full_confidence or self.full_confidence > 1
                or self.partial_risk_fraction > self.full_risk_fraction
                or self.full_risk_fraction > self.maximum_tail_loss_fraction
                or self.tail_gap_fraction >= 1
                or self.maximum_tail_loss_fraction > 1
                or self.minimum_free_collateral_fraction >= 1):
            raise ValueError("Invalid stress-risk policy fractions")
        if type(self.maximum_holding_bars) is not int or self.maximum_holding_bars < 1:
            raise ValueError("maximum_holding_bars must be a positive integer")


class StressAwareRiskManager:
    """Size by signal strength, then cap tail loss and funding-adjusted liquidation."""

    def __init__(self, settings: DerivativeSettings,
                 policy: StressRiskPolicy | None = None) -> None:
        self.settings = settings
        self.policy = policy or StressRiskPolicy()
        if self.policy.full_risk_fraction > settings.max_total_risk:
            raise ValueError("Full-confirmation risk exceeds the total-risk limit")

    @staticmethod
    def _deny(reason: str) -> DerivativeRiskDecision:
        return DerivativeRiskDecision(False, (reason,))

    def _tail_fill(self, stop: Decimal, direction: Direction) -> Decimal:
        policy, settings = self.policy, self.settings
        execution = settings.adverse_execution_bps / Decimal("10000")
        if direction == Direction.LONG:
            reference = stop * (Decimal("1") - policy.tail_gap_fraction)
            return floor_step(reference * (Decimal("1") - execution),
                              settings.contract.tick_size)
        reference = stop * (Decimal("1") + policy.tail_gap_fraction)
        return ceil_step(reference * (Decimal("1") + execution),
                         settings.contract.tick_size)

    def evaluate(self, signal: Signal, account,
                 context: DerivativeRiskContext) -> DerivativeRiskDecision:
        policy = self.policy
        if signal.confidence < policy.minimum_confidence:
            return self._deny("Signal agreement is below the stress-aware entry threshold.")
        risk_fraction = (policy.full_risk_fraction
                         if signal.confidence >= policy.full_confidence
                         else policy.partial_risk_fraction)
        tuned = replace(self.settings, max_risk_per_trade=risk_fraction)
        initial = LeveragedRiskManager(tuned).evaluate(signal, account, context)
        if not initial.allowed:
            return initial
        assert initial.entry_price is not None and initial.stop_price is not None

        entry, stop = initial.entry_price, initial.stop_price
        tail_fill = self._tail_fill(stop, signal.direction)
        if tail_fill <= 0:
            return self._deny("Tail-gap exit is not positive after rounding.")
        funding_fraction = policy.funding_stress_per_bar * policy.maximum_holding_bars
        unit_tail_loss = (
            abs(entry - tail_fill)
            + (entry + tail_fill) * self.settings.fee_rate
            + entry * funding_fraction
        )
        if unit_tail_loss <= 0:
            return self._deny("Tail-loss stress is invalid.")
        tail_budget = context.equity * policy.maximum_tail_loss_fraction
        tail_quantity = floor_step(
            tail_budget / unit_tail_loss, self.settings.contract.quantity_step
        )
        base_quantity = min(initial.quantity, tail_quantity)
        if base_quantity <= 0:
            return self._deny("Tail-loss budget leaves no executable quantity.")

        requested = int(signal.requested_leverage.to_integral_value(rounding=ROUND_FLOOR))
        maximum = min(
            10, requested, self.settings.max_leverage,
            self.settings.contract.maximum_leverage,
        )
        margin_budget = context.equity * self.settings.max_margin_fraction
        free_reserve = context.equity * policy.minimum_free_collateral_fraction
        choices = []
        for leverage in range(1, maximum + 1):
            per_unit_cash = entry / leverage + entry * (
                self.settings.fee_rate + funding_fraction
            )
            if account.balance <= free_reserve or per_unit_cash <= 0:
                continue
            quantity = floor_step(min(
                base_quantity,
                margin_budget * leverage / entry,
                (account.balance - free_reserve) / per_unit_cash,
            ), self.settings.contract.quantity_step)
            if quantity <= 0 or quantity * entry < self.settings.min_order_notional:
                continue
            required = max(1, int(
                (quantity * entry / margin_budget).to_integral_value(rounding=ROUND_CEILING)
            ))
            if required > leverage:
                continue
            initial_margin = quantity * entry / required
            funding_reserve = quantity * entry * funding_fraction
            # Build the same immutable position geometry that the PAPER broker will use.
            position = DerivativePosition(
                "stress-check", self.settings.contract, signal.direction, quantity,
                entry, required, context.timestamp,
                quantity * entry * self.settings.fee_rate,
                initial_margin,
                self.settings.contract.liquidation_price(entry, required, signal.direction),
                stop, initial.take_profit_price,
            )
            stressed_liquidation = dynamic_liquidation_price(position, funding_reserve)
            tail_before_liquidation = (
                tail_fill > stressed_liquidation if signal.direction == Direction.LONG
                else tail_fill < stressed_liquidation
            )
            if not tail_before_liquidation:
                continue
            normal_loss = initial.estimated_loss * quantity / initial.quantity
            choices.append((quantity, -required, required, initial_margin,
                            stressed_liquidation, normal_loss, funding_reserve))

        if not choices:
            return self._deny(
                "No position survives the tail-gap, funding, collateral and liquidation stress."
            )
        quantity, _, leverage, initial_margin, liquidation, normal_loss, funding_reserve = max(choices)
        return replace(
            initial,
            reasons=(
                f"Signal risk tier={risk_fraction}; normal stop risk remains capped.",
                f"Tail-gap plus funding stress is capped at {policy.maximum_tail_loss_fraction} of equity.",
                f"Smallest safe leverage for the retained quantity: {leverage}x.",
                f"Reserved adverse funding through {policy.maximum_holding_bars} bars: {funding_reserve}.",
            ),
            quantity=quantity,
            leverage=leverage,
            liquidation_price=liquidation,
            initial_margin=initial_margin,
            estimated_loss=normal_loss,
        )
