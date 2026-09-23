"""Stop-risk sizing and the smallest safe leverage for linear perpetuals."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from app.derivatives.models import DerivativeAccountSnapshot, PerpetualContract
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction, aware_timestamp, positive_decimal
from app.strategies.models import Signal


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def ceil_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


@dataclass(frozen=True)
class DerivativeRiskContext:
    price: Decimal
    timestamp: datetime
    equity: Decimal
    day_start_equity: Decimal
    peak_equity: Decimal
    daily_halted: bool = False
    drawdown_halted: bool = False
    kill_switch: bool = False

    def __post_init__(self) -> None:
        positive_decimal(self.price, "price")
        aware_timestamp(self.timestamp)
        for name in ("equity", "day_start_equity", "peak_equity"):
            positive_decimal(getattr(self, name), name, allow_zero=True)


@dataclass(frozen=True)
class DerivativeRiskDecision:
    allowed: bool
    reasons: tuple[str, ...]
    quantity: Decimal = Decimal("0")
    leverage: int = 1
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    liquidation_price: Decimal | None = None
    initial_margin: Decimal = Decimal("0")
    estimated_loss: Decimal = Decimal("0")


class LeveragedRiskManager:
    def __init__(self, settings: DerivativeSettings) -> None:
        self.settings = settings

    def _entry_fill(self, price: Decimal, direction: Direction) -> Decimal:
        fraction = self.settings.adverse_execution_bps / Decimal("10000")
        raw = price * (1 + fraction if direction == Direction.LONG else 1 - fraction)
        step = self.settings.contract.tick_size
        return ceil_step(raw, step) if direction == Direction.LONG else floor_step(raw, step)

    def _exit_fill(self, price: Decimal, direction: Direction) -> Decimal:
        fraction = self.settings.adverse_execution_bps / Decimal("10000")
        raw = price * (1 - fraction if direction == Direction.LONG else 1 + fraction)
        step = self.settings.contract.tick_size
        return floor_step(raw, step) if direction == Direction.LONG else ceil_step(raw, step)

    def evaluate(self, signal: Signal, account: DerivativeAccountSnapshot,
                 context: DerivativeRiskContext) -> DerivativeRiskDecision:
        def deny(reason: str) -> DerivativeRiskDecision:
            return DerivativeRiskDecision(False, (reason,))

        if context.kill_switch:
            return deny("Kill switch is active.")
        if context.daily_halted or context.drawdown_halted:
            return deny("Loss limit has halted new derivative entries.")
        if signal.timestamp > context.timestamp:
            return deny("Signal is from the future.")
        if signal.symbol != self.settings.contract.symbol:
            return deny("Signal market differs from the perpetual contract.")
        if signal.direction not in (Direction.LONG, Direction.SHORT):
            return deny("Only LONG or SHORT can open a perpetual position.")
        if account.position is not None:
            return deny("Only one derivative position is allowed.")
        if signal.stop_price is None or context.equity <= 0:
            return deny("A stop and positive equity are required.")

        contract = self.settings.contract
        entry = self._entry_fill(context.price, signal.direction)
        if signal.direction == Direction.LONG:
            stop = floor_step(signal.stop_price, contract.tick_size)
            target = (ceil_step(signal.take_profit_price, contract.tick_size)
                      if signal.take_profit_price is not None else None)
            if stop <= 0 or stop >= entry or (target is not None and target <= entry):
                return deny("LONG stop/target is invalid after executable rounding.")
        else:
            stop = ceil_step(signal.stop_price, contract.tick_size)
            target = (floor_step(signal.take_profit_price, contract.tick_size)
                      if signal.take_profit_price is not None else None)
            if stop <= entry or (target is not None and (target <= 0 or target >= entry)):
                return deny("SHORT stop/target is invalid after executable rounding.")

        stop_fill = self._exit_fill(stop, signal.direction)
        unit_loss = abs(entry - stop_fill) + (entry + stop_fill) * self.settings.fee_rate
        loss_used = max(Decimal("0"), context.day_start_equity - context.equity)
        drawdown_used = max(Decimal("0"), context.peak_equity - context.equity)
        budget = min(
            context.equity * self.settings.max_risk_per_trade,
            context.equity * self.settings.max_total_risk,
            context.day_start_equity * self.settings.max_daily_loss - loss_used,
            context.peak_equity * self.settings.max_drawdown - drawdown_used,
        )
        requested = int(signal.requested_leverage.to_integral_value(rounding=ROUND_FLOOR))
        maximum = min(self.settings.max_leverage, contract.maximum_leverage, requested)
        if budget <= 0 or unit_loss <= 0 or maximum < 1:
            return deny("No loss budget or permitted leverage remains.")
        margin_budget = context.equity * self.settings.max_margin_fraction
        max_notional = min(self.settings.max_position_notional, margin_budget * maximum)
        quantity = floor_step(min(budget / unit_loss, max_notional / entry), contract.quantity_step)
        if quantity <= 0 or quantity * entry < self.settings.min_order_notional:
            return deny("Risk-sized order is below the derivative minimum.")

        notional = quantity * entry
        required = max(1, int((notional / margin_budget).to_integral_value(rounding=ROUND_CEILING)))
        if required > maximum:
            return deny("Position cannot fit the allowed collateral and leverage.")
        liquidation = contract.liquidation_price(entry, required, signal.direction)
        required_distance = abs(entry - stop) + entry * self.settings.min_liquidation_buffer
        if abs(entry - liquidation) < required_distance:
            return deny("Liquidation is too close to the protective stop.")
        initial_margin = notional / required
        entry_fee = notional * self.settings.fee_rate
        if initial_margin + entry_fee > account.balance:
            return deny("Insufficient account balance for margin and entry fee.")
        return DerivativeRiskDecision(
            True,
            ("Size is capped by stop loss, fees, account loss limits and collateral.",
             f"Smallest required safe leverage selected: {required}x of {maximum}x allowed."),
            quantity, required, entry, stop, target, liquidation, initial_margin,
            quantity * unit_loss,
        )
