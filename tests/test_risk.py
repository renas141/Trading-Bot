import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from app.config.settings import RiskLimits, Settings
from app.database.repository import Repository
from app.domain import Direction
from app.errors import SimulationError
from app.execution.costs import ExecutionCosts
from app.execution.paper_broker import PaperBroker
from app.portfolio.models import PortfolioSnapshot, Position
from app.risk.state import RiskState
from app.risk.stop_risk import StopRiskManager
from tests.helpers import D, NOW, signal


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(paper_fee_rate=D("0"), paper_slippage_bps=D("0"))
        self.portfolio = PortfolioSnapshot(D("1000"), (), D("0"))
        self.context = RiskState(D("1000"), self.settings.risk).observe(D("100"), NOW, D("1000"))
        self.signal = replace(signal(), stop_price=D("90"))

    def evaluate(self, settings=None, portfolio=None, context=None, trade_signal=None):
        return StopRiskManager(settings or self.settings).evaluate(
            trade_signal or self.signal, portfolio or self.portfolio, context or self.context)

    def test_one_percent_risk_sizes_from_stop_distance(self):
        decision = self.evaluate()
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.quantity, D("1"))
        self.assertEqual(decision.estimated_loss, D("10"))

    def test_costs_reduce_quantity_and_loss_includes_both_fees(self):
        settings = replace(self.settings, paper_fee_rate=D("0.01"), paper_slippage_bps=D("100"), paper_spread_bps=D("100"))
        decision = self.evaluate(settings=settings)
        # Entry 101.50 + 1% fee; stop fill 88.65 minus 1% exit fee.
        unit_loss = D("101.50") * D("1.01") - D("88.65") * D("0.99")
        self.assertTrue(decision.allowed)
        self.assertLess(decision.quantity, D("1"))
        self.assertEqual(decision.estimated_loss, decision.quantity * unit_loss)
        self.assertLessEqual(decision.estimated_loss, D("10"))

    def test_existing_positions_consume_total_risk(self):
        limits = replace(self.settings.risk, max_positions=3, max_total_risk=D("0.015"))
        position = Position("p", "BTC/EUR", Direction.LONG, D("1"), D("100"), NOW, D("0"), stop_price=D("90"))
        portfolio = PortfolioSnapshot(D("900"), (position,), D("0"))
        decision = self.evaluate(settings=replace(self.settings, risk=limits), portfolio=portfolio)
        self.assertEqual(decision.quantity, D("0.5"))
        self.assertEqual(decision.estimated_loss, D("5"))

    def test_daily_and_drawdown_remaining_budget_reduce_size(self):
        context = replace(self.context, equity=D("975"))
        decision = self.evaluate(context=context)
        self.assertEqual(decision.quantity, D("0.5"))  # 30 daily budget less 25 used.
        context = replace(self.context, equity=D("905"), day_start_equity=D("905"))
        decision = self.evaluate(context=context)
        self.assertEqual(decision.quantity, D("0.5"))  # 100 drawdown budget less 95 used.

    def test_cash_and_notional_caps(self):
        self.assertEqual(self.evaluate(portfolio=replace(self.portfolio, cash=D("50"))).quantity, D("0.5"))
        settings = replace(self.settings, risk=replace(self.settings.risk, max_position_notional=D("25")))
        self.assertEqual(self.evaluate(settings=settings).quantity, D("0.25"))

    def test_rounding_never_increases_quantity_or_improves_fill(self):
        settings = replace(self.settings, quantity_step=D("0.3"), price_tick=D("0.5"))
        decision = self.evaluate(settings=settings, trade_signal=replace(self.signal, stop_price=D("90.4")))
        self.assertEqual(decision.stop_price, D("90"))
        self.assertEqual(decision.quantity, D("0.9"))
        costs = ExecutionCosts(settings)
        self.assertEqual(costs.buy(D("100.1")), D("100.5"))
        self.assertEqual(costs.sell(D("100.1")), D("100"))

    def test_missing_stop_short_leverage_invalid_target_and_tiny_size_denied(self):
        for changes in ({"stop_price": None}, {"direction": Direction.SHORT}, {"direction": Direction.HOLD},
                        {"requested_leverage": D("2")}, {"stop_price": D("100")},
                        {"take_profit_price": D("99")}, {"timestamp": NOW + timedelta(seconds=1)}):
            with self.subTest(changes=changes):
                self.assertFalse(self.evaluate(trade_signal=replace(self.signal, **changes)).allowed)
        self.assertFalse(self.evaluate(portfolio=replace(self.portfolio, cash=D("1"))).allowed)
        self.assertFalse(StopRiskManager(self.settings).evaluate(self.signal, self.portfolio).allowed)

    def test_base_asset_minimum_is_enforced_even_when_notional_passes(self):
        settings = replace(self.settings, min_order_quantity=D("1.01"))
        self.assertFalse(self.evaluate(settings=settings).allowed)
        self.assertTrue(self.evaluate(settings=replace(settings, min_order_quantity=D("1"))).allowed)
        with tempfile.TemporaryDirectory() as directory, Repository(Path(directory) / "test.db") as repository:
            session = repository.start_session(settings.mode, D("1000"), "BTC/EUR")
            broker = PaperBroker(settings, repository, session)
            with self.assertRaises(SimulationError):
                broker.open_position(self.signal, self.evaluate(), D("100"))

    def test_latched_limits_and_kill_switch_deny(self):
        for flag in ("daily_halted", "drawdown_halted", "kill_switch"):
            with self.subTest(flag=flag):
                self.assertFalse(self.evaluate(context=replace(self.context, **{flag: True})).allowed)

    def test_daily_halt_survives_recovery_and_resets_next_utc_day(self):
        state = RiskState(D("1000"), self.settings.risk)
        state.observe(D("100"), NOW, D("1000"))
        self.assertTrue(state.observe(D("97"), NOW + timedelta(hours=1), D("970")).daily_halted)
        self.assertTrue(state.observe(D("100"), NOW + timedelta(hours=2), D("1000")).daily_halted)
        self.assertFalse(state.observe(D("100"), NOW + timedelta(days=1), D("1000")).daily_halted)

    def test_drawdown_halt_survives_recovery_and_new_day(self):
        state = RiskState(D("1000"), self.settings.risk)
        self.assertTrue(state.observe(D("90"), NOW, D("900")).drawdown_halted)
        self.assertTrue(state.observe(D("100"), NOW + timedelta(days=1), D("1000")).drawdown_halted)

    def test_new_day_opening_gap_counts_toward_daily_loss(self):
        state = RiskState(D("1000"), self.settings.risk)
        state.observe(D("100"), NOW + timedelta(hours=23), D("1000"))
        context = state.observe(D("96"), NOW + timedelta(days=1), D("960"))
        self.assertEqual(context.day_start_equity, D("1000"))
        self.assertTrue(context.daily_halted)

    def test_risk_time_cannot_move_backwards(self):
        state = RiskState(D("1000"), self.settings.risk)
        state.observe(D("100"), NOW, D("1000"))
        with self.assertRaises(ValueError):
            state.observe(D("100"), NOW - timedelta(seconds=1), D("1000"))

    def test_broker_rechecks_forged_size_and_runtime_kill_allows_exit(self):
        with tempfile.TemporaryDirectory() as directory, Repository(Path(directory) / "test.db") as repository:
            session = repository.start_session(self.settings.mode, D("1000"), "BTC/EUR")
            broker = PaperBroker(self.settings, repository, session)
            decision = self.evaluate()
            with self.assertRaises(SimulationError):
                broker.open_position(self.signal, replace(decision, quantity=D("2")), D("100"))
            with self.assertRaises(SimulationError):
                broker.open_position(self.signal, replace(decision, quantity=D("0.01")), D("100"))
            order = broker.open_position(self.signal, decision, D("100"))
            broker.trip_kill_switch()
            broker.close_position(order.position_id, D("101"), NOW, "protective exit")
            with self.assertRaises(SimulationError):
                broker.open_position(self.signal, decision, D("100"))
            self.assertEqual(broker.snapshot().cash, D("1001"))
