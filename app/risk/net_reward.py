"""Optional research-only filter on the existing stop-risk policy."""

from dataclasses import replace
from decimal import Decimal

from app.config.settings import Settings
from app.domain import TradingMode, positive_decimal
from app.portfolio.models import PortfolioSnapshot
from app.risk.risk_manager import RiskDecision
from app.risk.state import RiskContext
from app.risk.stop_risk import StopRiskManager
from app.strategies.models import Signal

REJECTION = "Net reward at target is below the required stop risk multiple."


class NetRewardRiskManager(StopRiskManager):
    """Keep the original target and size; require sufficient reward after costs.

    Evaluated at the execution reference, not the preceding signal close.
    This is a research selection rule, not a profit probability estimate.
    """

    def __init__(self, settings: Settings, minimum_ratio: Decimal = Decimal("1")) -> None:
        if settings.mode != TradingMode.BACKTEST:
            raise ValueError("Net-reward policy is available only for BACKTEST research")
        positive_decimal(minimum_ratio, "minimum_ratio")
        if minimum_ratio < 1:
            raise ValueError("Research requires a net reward/risk ratio of at least one")
        super().__init__(settings)
        self.minimum_ratio = minimum_ratio

    def evaluate(self, signal: Signal, portfolio: PortfolioSnapshot,
                 context: RiskContext | None = None) -> RiskDecision:
        decision = super().evaluate(signal, portfolio, context)
        if not decision.allowed:
            return decision
        if decision.take_profit_price is None:
            return RiskDecision(False, ("Net-reward policy requires an explicit target.",))
        entry = self.costs.entry_cost(context.price)
        reward = self.costs.exit_value(decision.take_profit_price) - entry
        risk = entry - self.costs.exit_value(decision.stop_price)
        detail = (f"Net reward/unit={reward}; stop risk/unit={risk}; "
                  f"required reward/risk={self.minimum_ratio}; evaluated at next-open reference={context.price}.")
        if reward < self.minimum_ratio * risk:
            return RiskDecision(False, (REJECTION, detail))
        return replace(decision, reasons=decision.reasons + ("Net reward/risk filter passed.", detail))
