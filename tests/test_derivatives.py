import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from app.derivatives.broker import DerivativePaperBroker
from app.derivatives.models import DerivativeAccountSnapshot, PerpetualContract
from app.derivatives.risk import DerivativeRiskContext, LeveragedRiskManager
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction
from app.strategies.models import Signal


D = Decimal
NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def trade_signal(direction=Direction.LONG, stop="90", target="120", leverage="10"):
    return Signal(
        "BTC/USD", NOW, direction, D("1"), ("Fixed derivative unit-test signal",),
        "test", "1", D(stop), D(target) if target else None, D(leverage),
    )


class DerivativeTests(unittest.TestCase):
    def setUp(self):
        self.settings = DerivativeSettings(fee_rate=D("0"), slippage_bps=D("0"))
        self.account = DerivativeAccountSnapshot(D("1000"), D("1000"), D("1000"), None, D("0"))
        self.context = DerivativeRiskContext(D("100"), NOW, D("1000"), D("1000"), D("1000"))

    def evaluate(self, signal=None, settings=None):
        return LeveragedRiskManager(settings or self.settings).evaluate(
            signal or trade_signal(), self.account, self.context,
        )

    def test_contract_caps_europe_retail_assumption_at_ten_x(self):
        contract = PerpetualContract()
        self.assertEqual(contract.maximum_leverage, 10)
        self.assertEqual(contract.liquidation_price(D("100"), 10, Direction.LONG), D("90") / D("0.95"))
        self.assertEqual(contract.liquidation_price(D("100"), 10, Direction.SHORT), D("110") / D("1.05"))

    def test_risk_manager_selects_smallest_needed_leverage(self):
        decision = self.evaluate(trade_signal(stop="99", target="102"))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.quantity, D("10"))
        self.assertEqual(decision.estimated_loss, D("10"))
        self.assertEqual(decision.leverage, 4)
        self.assertEqual(decision.initial_margin, D("250"))

    def test_ten_x_is_available_but_liquidation_buffer_can_reject_it(self):
        settings = replace(self.settings, max_margin_fraction=D("0.01"))
        allowed = self.evaluate(trade_signal(stop="97", target="106"), settings)
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.leverage, 10)
        denied = self.evaluate(trade_signal(stop="90", target="120"), settings)
        self.assertFalse(denied.allowed)
        self.assertIn("Liquidation", denied.reasons[0])

    def test_requested_leverage_is_a_cap_and_position_is_reduced(self):
        decision = self.evaluate(trade_signal(stop="99", target="102", leverage="2"))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.leverage, 2)
        self.assertEqual(decision.quantity, D("5"))
        self.assertEqual(decision.estimated_loss, D("5"))

    def test_short_sizing_and_geometry(self):
        decision = self.evaluate(trade_signal(Direction.SHORT, stop="101", target="98"))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.quantity, D("10"))
        self.assertEqual(decision.leverage, 4)
        self.assertLess(decision.entry_price, decision.stop_price)
        self.assertGreater(decision.liquidation_price, decision.stop_price)

    def test_spread_and_slippage_are_separate_and_used_by_risk_and_broker(self):
        contract = PerpetualContract(tick_size=D("0.01"))
        settings = replace(
            self.settings, contract=contract, spread_bps=D("20"), slippage_bps=D("10"),
            max_margin_fraction=D("1"),
        )
        self.assertEqual(settings.adverse_execution_bps, D("20"))
        signal = trade_signal(stop="90", target="120")
        manager = LeveragedRiskManager(settings)
        decision = manager.evaluate(signal, self.account, self.context)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.entry_price, D("100.20"))
        self.assertEqual(decision.quantity, D("0.9633"))
        self.assertEqual(decision.estimated_loss, D("0.9633") * D("10.38"))
        broker = DerivativePaperBroker(settings)
        broker.open_position(signal, decision, NOW)
        trade = broker.close_position(D("110"), NOW, "TEST")
        self.assertEqual(trade.exit_price, D("109.78"))
        self.assertEqual(trade.net_pnl, D("0.9633") * D("9.58"))

    def test_combined_spread_and_slippage_cannot_reach_one_hundred_percent(self):
        with self.assertRaises(ValueError):
            DerivativeSettings(spread_bps=D("2"), slippage_bps=D("9999"))
        with self.assertRaises(ValueError):
            DerivativeSettings(spread_bps=D("-1"))

    def test_long_funding_fee_and_pnl_reconcile_to_balance(self):
        settings = replace(self.settings, max_margin_fraction=D("1"))
        broker = DerivativePaperBroker(settings)
        decision = LeveragedRiskManager(settings).evaluate(
            trade_signal(stop="90", target="120"), broker.snapshot(), self.context,
        )
        position = broker.open_position(trade_signal(stop="90", target="120"), decision, NOW)
        payment = broker.apply_funding(D("0.01"), D("100"))
        trade = broker.close_position(D("110"), NOW, "TEST")
        self.assertEqual(position.quantity, D("1"))
        self.assertEqual(payment, D("1"))
        self.assertEqual(trade.net_pnl, D("9"))
        self.assertEqual(broker.snapshot().balance, D("1009"))

    def test_positive_funding_is_received_by_short(self):
        settings = replace(self.settings, max_margin_fraction=D("1"))
        broker = DerivativePaperBroker(settings)
        signal = trade_signal(Direction.SHORT, stop="110", target="80")
        decision = LeveragedRiskManager(settings).evaluate(signal, broker.snapshot(), self.context)
        broker.open_position(signal, decision, NOW)
        self.assertEqual(broker.apply_funding(D("0.01"), D("100")), D("-1"))
        trade = broker.close_position(D("90"), NOW, "TEST")
        self.assertEqual(trade.net_pnl, D("11"))
        self.assertEqual(broker.snapshot().balance, D("1011"))


if __name__ == "__main__":
    unittest.main()
