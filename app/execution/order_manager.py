"""Only application route from a strategy signal to simulated execution."""

import logging
from datetime import datetime
from decimal import Decimal

from app.database.repository import Repository
from app.domain import Direction
from app.execution.base import Broker, Execution
from app.risk.risk_manager import RiskDecision, RiskManager
from app.strategies.models import Signal

logger = logging.getLogger(__name__)


class OrderManager(Execution):
    def __init__(self, risk: RiskManager, broker: Broker, repository: Repository, session_id: str) -> None:
        self.risk = risk
        self.broker = broker
        self.repository = repository
        self.session_id = session_id

    def submit(self, signal: Signal, price: Decimal, timestamp: datetime | None = None) -> RiskDecision:
        timestamp = timestamp or signal.timestamp
        context = self.broker.mark(price, timestamp)
        decision = self.risk.evaluate(signal, self.broker.snapshot(), context)
        if signal.direction == Direction.HOLD:
            decision = RiskDecision(False, ("Strategy recommends no trade.",) + decision.reasons)
        self.repository.record_signal(self.session_id, signal, decision)
        logger.info("Signal evaluated symbol=%s direction=%s allowed=%s", signal.symbol,
                    signal.direction.value, decision.allowed)
        if decision.allowed:
            self.broker.open_position(signal, decision, price, timestamp)
        return decision
