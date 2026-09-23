import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.config.settings import Settings
from app.database.repository import Repository
from app.domain import TradingMode
from app.errors import SimulationError
from app.execution.paper_broker import PaperBroker
from app.portfolio.models import PortfolioSnapshot
from app.risk.net_reward import NetRewardRiskManager, REJECTION
from app.risk.state import RiskState
from app.risk.stop_risk import StopRiskManager
from tests.helpers import D, NOW, signal


class NetRewardTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(mode=TradingMode.BACKTEST, paper_fee_rate=D("0"), paper_slippage_bps=D("0"))
        self.portfolio = PortfolioSnapshot(D("1000"), (), D("0"))
        self.context = RiskState(D("1000"), self.settings.risk).observe(D("100"), NOW, D("1000"))
        self.signal = replace(signal(), stop_price=D("90"), take_profit_price=D("110"))

    def test_exact_one_to_one_boundary_passes_without_changing_size_or_prices(self):
        original = StopRiskManager(self.settings).evaluate(self.signal, self.portfolio, self.context)
        actual = NetRewardRiskManager(self.settings).evaluate(self.signal, self.portfolio, self.context)
        self.assertTrue(actual.allowed)
        self.assertEqual(actual.quantity, D("1"))
        self.assertEqual(replace(actual, reasons=original.reasons), original)

    def test_higher_next_open_can_reject_same_signal(self):
        decision = NetRewardRiskManager(self.settings).evaluate(self.signal, self.portfolio, replace(self.context, price=D("101")))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reasons[0], REJECTION)
        self.assertEqual(decision.quantity, 0)

    def test_costs_make_positive_raw_target_insufficient(self):
        settings = replace(self.settings, paper_fee_rate=D("0.0026"), paper_slippage_bps=D("5"), paper_spread_bps=D("10"))
        candidate = replace(self.signal, stop_price=D("99"), take_profit_price=D("100.5"))
        self.assertTrue(StopRiskManager(settings).evaluate(candidate, self.portfolio, self.context).allowed)
        actual = NetRewardRiskManager(settings).evaluate(candidate, self.portfolio, self.context)
        self.assertFalse(actual.allowed)
        self.assertIn("Net reward/unit=-", actual.reasons[1])

    def test_positive_net_target_can_still_have_insufficient_reward_to_risk(self):
        settings = replace(self.settings, paper_fee_rate=D("0.01"))
        # At zero costs 20/10 passes, but 2% fees leave (118.8-101)/(101-89.1) > 1.
        passing = replace(self.signal, take_profit_price=D("120"))
        self.assertTrue(NetRewardRiskManager(settings).evaluate(passing, self.portfolio, self.context).allowed)
        # Target 112 still yields +9.88/unit net, less than 11.90/unit risk.
        failing = replace(self.signal, take_profit_price=D("112"))
        result = NetRewardRiskManager(settings).evaluate(failing, self.portfolio, self.context)
        self.assertFalse(result.allowed)
        self.assertIn("Net reward/unit=9.88", result.reasons[1])

    def test_missing_target_and_invalid_mode_or_ratio_rejected(self):
        self.assertFalse(NetRewardRiskManager(self.settings).evaluate(replace(self.signal, take_profit_price=None), self.portfolio, self.context).allowed)
        for ratio in (D("0"), D("0.9"), D("NaN")):
            with self.assertRaises(ValueError):
                NetRewardRiskManager(self.settings, ratio)
        with self.assertRaises(ValueError):
            NetRewardRiskManager(replace(self.settings, mode=TradingMode.PAPER))

    def test_original_limits_keep_priority(self):
        for flag in ("daily_halted", "drawdown_halted", "kill_switch"):
            context = replace(self.context, **{flag: True})
            self.assertEqual(NetRewardRiskManager(self.settings).evaluate(self.signal, self.portfolio, context),
                             StopRiskManager(self.settings).evaluate(self.signal, self.portfolio, context))

    def test_broker_rechecks_filter_even_with_original_policy_approval(self):
        with tempfile.TemporaryDirectory() as directory, Repository(Path(directory) / "test.db") as repo:
            session = repo.start_session(self.settings.mode, D("1000"), "BTC/EUR")
            broker = PaperBroker(self.settings, repo, session)
            broker.risk_guard = NetRewardRiskManager(self.settings)
            candidate = replace(self.signal, take_profit_price=D("105"))
            approval = StopRiskManager(self.settings).evaluate(candidate, self.portfolio, self.context)
            self.assertTrue(approval.allowed)
            with self.assertRaises(SimulationError):
                broker.open_position(candidate, approval, D("100"))
            self.assertEqual(broker.snapshot(), self.portfolio)
            self.assertEqual(repo.records("orders", session), [])
