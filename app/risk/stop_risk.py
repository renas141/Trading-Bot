"""Stop-based sizing for cash-funded BTC/EUR LONG simulations only."""

from decimal import Decimal

from app.config.settings import Settings
from app.domain import Direction
from app.execution.costs import ExecutionCosts, ceil_step, floor_step
from app.portfolio.models import PortfolioSnapshot
from app.risk.risk_manager import RiskDecision, RiskManager
from app.risk.state import RiskContext
from app.strategies.models import Signal


class StopRiskManager(RiskManager):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.costs = ExecutionCosts(settings)

    def evaluate(self, signal: Signal, portfolio: PortfolioSnapshot,
                 context: RiskContext | None = None) -> RiskDecision:
        limits = self.settings.risk

        def deny(reason: str) -> RiskDecision:
            return RiskDecision(False, (reason,))

        if context is None:
            return deny("No current execution price and portfolio risk context.")
        if limits.kill_switch or context.kill_switch:
            return deny("Kill switch is active.")
        if context.daily_halted:
            return deny("Daily loss limit reached; entries halted for this UTC day.")
        if context.drawdown_halted:
            return deny("Drawdown limit reached; entries halted for this session.")
        if signal.timestamp > context.timestamp:
            return deny("Signal is from the future.")
        if signal.symbol != self.settings.symbol:
            return deny("Signal market differs from the configured account.")
        if signal.direction != Direction.LONG:
            return deny("Only cash-funded LONG entries are supported; HOLD/SHORT cannot open positions.")
        if signal.requested_leverage != 1:
            return deny("Only 1x execution is supported, regardless of the configured leverage cap.")
        if len(portfolio.positions) >= limits.max_positions:
            return deny("Maximum position count reached.")
        if signal.stop_price is None:
            return deny("An explicit protective stop is required.")
        stop = floor_step(signal.stop_price, self.settings.price_tick)
        if stop <= 0 or stop >= context.price:
            return deny("Stop must be below the current entry reference after rounding.")
        target = (ceil_step(signal.take_profit_price, self.settings.price_tick)
                  if signal.take_profit_price is not None else None)
        if target is not None and target <= self.costs.buy(context.price):
            return deny("Take profit must exceed the simulated entry fill.")
        if context.equity <= 0:
            return deny("No positive equity available.")
        try:
            entry_cost = self.costs.entry_cost(context.price)
            unit_risk = entry_cost - self.costs.exit_value(stop)
            open_risk = Decimal("0")
            for position in portfolio.positions:
                if position.symbol != signal.symbol or position.stop_price is None or position.direction != Direction.LONG:
                    return deny("Existing portfolio exposure cannot be valued safely.")
                open_risk += position.quantity * max(Decimal("0"),
                    self.costs.exit_value(context.price) - self.costs.exit_value(position.stop_price))
        except ValueError:
            return deny("Price or stop is below the executable simulation tick.")
        budget = min(
            context.equity * limits.max_risk_per_trade,
            context.equity * limits.max_total_risk - open_risk,
            context.day_start_equity * limits.max_daily_loss
            - max(Decimal("0"), context.day_start_equity - context.equity) - open_risk,
            context.peak_equity * limits.max_drawdown
            - (context.peak_equity - context.equity) - open_risk,
        )
        if budget <= 0 or unit_risk <= 0:
            return deny("No remaining loss budget after existing portfolio risk.")
        quantity = floor_step(min(budget / unit_risk, portfolio.cash / entry_cost,
                                  limits.max_position_notional / self.costs.buy(context.price)),
                              self.settings.quantity_step)
        if (quantity <= 0 or quantity < self.settings.min_order_quantity
                or quantity * self.costs.buy(context.price) < self.settings.min_order_notional):
            return deny("Allowed size is below the simulation minimum after rounding.")
        return RiskDecision(True,
                            ("Stop-based position size includes entry/exit fees, spread, slippage and rounding.",
                             "Per-trade, total, daily, drawdown, cash and position limits passed."),
                            quantity, Decimal("1"), stop, target, quantity * unit_risk)
