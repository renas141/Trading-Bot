import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app.config.settings import Settings
from app.database.repository import Repository
from app.domain import Direction, TradingMode
from app.errors import SimulationError
from app.execution.durable_paper import DurablePaperBroker
from app.execution.order_manager import OrderManager
from app.risk.stop_risk import StopRiskManager
from app.strategies.models import Signal
from tests.helpers import D, NOW


class DurablePaperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "paper.sqlite3"
        self.repo = Repository(self.path)
        self.addCleanup(self.repo.connection.close)
        self.settings = Settings(mode=TradingMode.PAPER, paper_fee_rate=D("0.0025"), paper_slippage_bps=D("5"))
        self.session = self.repo.start_session(TradingMode.PAPER, D("1000"), "BTC/EUR")
        self.broker = DurablePaperBroker(self.settings, self.repo, self.session)

    def enter(self):
        signal = Signal("BTC/EUR", NOW, Direction.LONG, D("1"), ("Recovery test fixture",), "test", "1", stop_price=D("90"))
        manager = OrderManager(StopRiskManager(self.settings), self.broker, self.repo, self.session)
        with self.broker.atomic():
            decision = manager.submit(signal, D("100"))
        self.assertTrue(decision.allowed)
        return self.broker.snapshot().positions[0].id

    def resume(self):
        return DurablePaperBroker.resume(self.settings, self.repo, self.session)

    def test_open_and_closed_portfolio_restores_exact_cash_fees_and_ledger(self):
        position_id = self.enter()
        self.broker.mark(D("110"), NOW + timedelta(minutes=1))
        before = self.broker.snapshot()
        peak = self.broker.risk_state.peak
        self.broker = self.resume()
        self.assertEqual(self.broker.snapshot(), before)
        self.assertEqual(self.broker.risk_state.peak, peak)
        trade = self.broker.close_position(position_id, D("105"), NOW + timedelta(minutes=2), "RECOVERY_TEST")
        self.broker = self.resume()
        self.assertEqual(self.broker.snapshot().positions, ())
        self.assertEqual(self.broker.trades, [trade])
        self.assertEqual(self.broker.snapshot().cash, D("1000") + trade.net_pnl)
        self.assertEqual(self.broker.total_fees, trade.fees)

    def test_durable_after_connection_close(self):
        self.enter()
        expected = self.broker.snapshot()
        self.repo.connection.close()
        self.repo = Repository(self.path)
        self.addCleanup(self.repo.connection.close)
        self.assertEqual(self.resume().snapshot(), expected)

    def test_peak_daily_drawdown_and_kill_latches_survive_restart(self):
        self.enter()
        self.broker.mark(D("300"), NOW + timedelta(minutes=1))
        self.broker.mark(D("1"), NOW + timedelta(minutes=2))
        self.broker.trip_kill_switch()
        recovered = self.resume()
        self.assertTrue(recovered.risk_state.daily_halted)
        self.assertTrue(recovered.risk_state.drawdown_halted)
        self.assertTrue(recovered.risk_state.kill_switch)
        self.assertEqual(recovered.risk_state.peak, self.broker.risk_state.peak)
        context = recovered.mark(D("100"), NOW + timedelta(days=1))
        self.assertFalse(context.daily_halted)
        self.assertTrue(context.drawdown_halted)
        self.assertTrue(context.kill_switch)

    def test_old_writer_rejected_after_resume_even_without_new_order(self):
        recovered = self.resume()
        with self.assertRaises(SimulationError):
            self.broker.mark(D("100"), NOW)
        self.assertIsNone(self.broker.risk_state.last_timestamp)
        recovered.mark(D("100"), NOW)

    def test_failed_checkpoint_after_close_rolls_back_all_memory_and_ledger(self):
        position_id = self.enter()
        before = self.broker.snapshot()
        orders = self.repo.records("orders", self.session)
        checkpoint = self.repo.records("paper_checkpoints", self.session)
        real_persist = self.broker._persist
        def fail_after_exit():
            if self.broker.trades:
                raise sqlite3.OperationalError("Injected checkpoint failure")
            real_persist()
        with patch.object(self.broker, "_persist", side_effect=fail_after_exit):
            with self.assertRaises(sqlite3.OperationalError):
                self.broker.close_position(position_id, D("105"), NOW + timedelta(minutes=1), "TEST")
        self.assertEqual(self.broker.snapshot(), before)
        self.assertEqual(self.repo.records("orders", self.session), orders)
        self.assertEqual(self.repo.records("trades", self.session), [])
        self.assertEqual(self.repo.records("paper_checkpoints", self.session), checkpoint)
        self.assertEqual(self.resume().snapshot(), before)

    def test_outer_unit_of_work_rolls_back_signal_and_entry_on_failure(self):
        with self.assertRaises(RuntimeError):
            with self.broker.atomic():
                self.enter()
                raise RuntimeError("Simulated crash before runner checkpoint")
        self.assertEqual(self.broker.snapshot().cash, D("1000"))
        self.assertEqual(self.broker.snapshot().positions, ())
        for table in ("signals", "orders", "positions", "trades"):
            self.assertEqual(self.repo.records(table, self.session), [])
        self.assertEqual(self.resume().snapshot(), self.broker.snapshot())

    def test_changed_costs_corruption_and_missing_ledger_fail_closed(self):
        self.enter()
        with self.assertRaises(SimulationError):
            DurablePaperBroker.resume(replace(self.settings, paper_fee_rate=D("0")), self.repo, self.session)
        with self.repo.transaction():
            self.repo.connection.execute("DELETE FROM orders WHERE session_id=?", (self.session,))
        with self.assertRaises(SimulationError):
            self.resume()

    def test_checkpoint_hash_checked_and_no_default_reinit(self):
        with self.assertRaises(SimulationError):
            DurablePaperBroker(self.settings, self.repo, self.session)
        with self.repo.transaction():
            self.repo.connection.execute("UPDATE paper_checkpoints SET payload='{}' WHERE session_id=?", (self.session,))
        with self.assertRaises(SimulationError):
            self.resume()

    def test_stopped_sessions_and_backtests_cannot_resume(self):
        self.repo.finish_session(self.session)
        with self.assertRaises(SimulationError):
            self.resume()
        with self.assertRaises(SimulationError):
            self.broker.mark(D("100"), NOW)
        with self.assertRaises(SimulationError):
            DurablePaperBroker.resume(replace(self.settings, mode=TradingMode.BACKTEST), self.repo, self.session)

    def test_migration_preserves_old_data_and_missing_checkpoint_is_not_guessed(self):
        other = self.repo.start_session(TradingMode.PAPER, D("1000"), "BTC/EUR")
        with self.assertRaises(SimulationError):
            DurablePaperBroker.resume(self.settings, self.repo, other)
        self.repo.connection.execute("PRAGMA user_version=2")
        with Repository(self.path) as upgraded:
            self.assertEqual(upgraded.connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(upgraded.records("sessions", other)[0]["initial_capital"], "1000")
