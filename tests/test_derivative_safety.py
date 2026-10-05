import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from app.derivatives.models import DerivativeAccountSnapshot
from app.derivatives.risk import DerivativeRiskContext
from app.derivatives.safety import (
    FundingAwarePaperBroker,
    StressAwareRiskManager,
    StressRiskPolicy,
    dynamic_liquidation_price,
    margin_health,
)
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction
from app.strategies.models import Signal


D = Decimal
NOW = datetime(2026, 10, 5, 16, tzinfo=timezone.utc)


def signal(direction=Direction.LONG, *, confidence="1", stop=None):
    stop = stop or ("99" if direction == Direction.LONG else "101")
    return Signal(
        "BTC/USD", NOW, direction, D(confidence), ("Safety fixture",),
        "future_candidate", "2", D(stop), None, D("10"),
    )


class DerivativeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.settings = DerivativeSettings(
            fee_rate=D("0"), spread_bps=D("0"), slippage_bps=D("0")
        )
        self.context = DerivativeRiskContext(
            D("100"), NOW, D("1000"), D("1000"), D("1000")
        )
        self.account = DerivativeAccountSnapshot(
            D("1000"), D("1000"), D("1000"), None, D("0")
        )

    def test_full_confirmation_can_risk_more_but_tail_budget_still_caps_it(self):
        manager = StressAwareRiskManager(self.settings)
        partial = manager.evaluate(signal(confidence=str(D(5) / D(6))), self.account,
                                   self.context)
        full = manager.evaluate(signal(confidence="1"), self.account, self.context)
        self.assertTrue(partial.allowed)
        self.assertTrue(full.allowed)
        self.assertGreater(full.quantity, partial.quantity)
        self.assertLessEqual(full.estimated_loss, D("12.5"))
        self.assertLessEqual(full.quantity * D("3.084"), D("30"))

    def test_weak_signal_is_denied_before_sizing(self):
        decision = StressAwareRiskManager(self.settings).evaluate(
            signal(confidence="0.8"), self.account, self.context
        )
        self.assertFalse(decision.allowed)
        self.assertIn("agreement", decision.reasons[0])

    def test_ten_x_long_and_short_can_open_and_close_when_stress_safe(self):
        settings = replace(self.settings, max_margin_fraction=D("0.01"))
        for direction in (Direction.LONG, Direction.SHORT):
            manager = StressAwareRiskManager(settings)
            decision = manager.evaluate(signal(direction), self.account, self.context)
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.leverage, 10)
            broker = FundingAwarePaperBroker(settings)
            broker.open_position(signal(direction), decision, NOW)
            self.assertFalse(broker.liquidation_required(D("100")))
            exit_price = D("101") if direction == Direction.LONG else D("99")
            trade = broker.close_position(exit_price, NOW, "SAFE_CLOSE")
            self.assertGreater(trade.net_pnl, D("0"))
            self.assertIsNone(broker.snapshot().position)

    def test_every_integer_leverage_from_one_to_ten_completes_both_directions(self):
        for leverage in range(1, 11):
            settings = replace(
                self.settings, max_leverage=leverage, max_margin_fraction=D("0.01")
            )
            for direction in (Direction.LONG, Direction.SHORT):
                decision = StressAwareRiskManager(settings).evaluate(
                    signal(direction), self.account, self.context
                )
                self.assertTrue(decision.allowed, (leverage, direction, decision.reasons))
                self.assertEqual(decision.leverage, leverage)
                broker = FundingAwarePaperBroker(settings)
                broker.open_position(signal(direction), decision, NOW)
                broker.close_position(D("100"), NOW, "LIFECYCLE_CHECK")
                self.assertIsNone(broker.snapshot().position)

    def test_large_tail_gap_reduces_exposure_and_leverage(self):
        settings = replace(self.settings, max_margin_fraction=D("0.01"))
        normal = StressAwareRiskManager(settings).evaluate(
            signal(), self.account, self.context
        )
        stressed = StressAwareRiskManager(
            settings, replace(StressRiskPolicy(), tail_gap_fraction=D("0.10"))
        ).evaluate(signal(), self.account, self.context)
        self.assertTrue(normal.allowed)
        self.assertTrue(stressed.allowed)
        self.assertEqual(normal.leverage, 10)
        self.assertLess(stressed.quantity, normal.quantity)
        self.assertLess(stressed.leverage, normal.leverage)

    def test_paid_funding_moves_dynamic_liquidation_toward_entry(self):
        settings = replace(self.settings, max_margin_fraction=D("0.01"))
        for direction in (Direction.LONG, Direction.SHORT):
            decision = StressAwareRiskManager(settings).evaluate(
                signal(direction), self.account, self.context
            )
            broker = FundingAwarePaperBroker(settings)
            position = broker.open_position(signal(direction), decision, NOW)
            before = dynamic_liquidation_price(position)
            after = dynamic_liquidation_price(position, D("1"))
            if direction == Direction.LONG:
                self.assertGreater(after, before)
            else:
                self.assertLess(after, before)
            crossed = after - D("0.01") if direction == Direction.LONG else after + D("0.01")
            health = margin_health(position, crossed, D("1"))
            self.assertTrue(health.liquidatable)


if __name__ == "__main__":
    unittest.main()
