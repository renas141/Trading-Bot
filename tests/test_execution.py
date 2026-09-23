import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.config.settings import RiskLimits, Settings
from app.database.repository import Repository
from app.domain import Direction
from app.errors import SimulationError
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import PaperBroker
from app.risk.risk_manager import RejectAllRiskManager, RiskDecision
from tests.helpers import D, NOW, signal


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "test.sqlite3"
        self.repository = Repository(self.path)
        self.addCleanup(self.repository.connection.close)
        self.settings = Settings(paper_fee_rate=D("0.01"), paper_slippage_bps=D("100"))
        self.session = self.repository.start_session(self.settings.mode, D("1000"), "BTC/EUR")
        self.broker = PaperBroker(self.settings, self.repository, self.session)
        self.approved = RiskDecision(True, ("Unit test approval; independently revalidated",), D("2"), stop_price=D("99"))

    def test_cash_fees_slippage_and_trade_persist_exactly(self):
        order = self.broker.open_position(signal(), self.approved, D("100"))
        self.assertEqual(order.fill_price, D("101"))
        self.assertEqual(self.broker.snapshot().cash, D("795.98"))
        trade = self.broker.close_position(order.position_id, D("110"), NOW, "Test exit")
        self.assertEqual(trade.net_pnl, D("11.602"))
        self.assertEqual(self.broker.snapshot().cash, D("1011.602"))
        self.assertEqual(self.broker.snapshot().realized_pnl, D("11.602"))
        self.assertEqual(self.broker.snapshot().positions, ())
        with Repository(self.path) as second_connection:
            self.assertEqual(len(second_connection.records("orders", self.session)), 2)
            self.assertEqual(second_connection.records("positions", self.session)[0]["status"], "CLOSED")
            persisted = second_connection.records("trades", self.session)[0]
            self.assertEqual(D(persisted["net_pnl"]), D("11.602"))
            self.assertEqual(json.loads(persisted["payload"])["exit_reason"], "Test exit")

    def test_default_risk_gate_never_calls_broker_and_records_why(self):
        manager = OrderManager(RejectAllRiskManager(self.settings.risk), self.broker, self.repository, self.session)
        with patch.object(self.broker, "open_position") as open_position:
            decision = manager.submit(signal(), D("100"))
            open_position.assert_not_called()
        self.assertFalse(decision.allowed)
        saved = self.repository.records("signals", self.session)[0]
        self.assertFalse(json.loads(saved["risk_decision"])["allowed"])
        self.assertEqual(json.loads(saved["payload"])["strategy_version"], "1")

    def test_rejected_short_leveraged_and_wrong_symbol_entries(self):
        cases = [(signal(), RiskDecision(False, ("Denied",))),
                 (signal(Direction.SHORT), self.approved),
                 (signal(), replace(self.approved, leverage=D("2"))),
                 (replace(signal(), symbol="BTC/USD"), self.approved)]
        for trade_signal, decision in cases:
            with self.subTest(direction=trade_signal.direction), self.assertRaises(SimulationError):
                self.broker.open_position(trade_signal, decision, D("100"))
        self.assertEqual(self.broker.snapshot().cash, D("1000"))
        self.assertEqual(self.repository.records("orders", self.session), [])

    def test_insufficient_cash_includes_fees_and_slippage(self):
        with self.assertRaises(SimulationError):
            self.broker.open_position(signal(), replace(self.approved, quantity=D("9.9")), D("100"))

    def test_position_count_and_notional_caps(self):
        with self.assertRaises(SimulationError):
            self.broker.open_position(signal(), replace(self.approved, quantity=D("11")), D("100"))
        self.broker.open_position(signal(), self.approved, D("100"))
        with self.assertRaises(SimulationError):
            self.broker.open_position(signal(), self.approved, D("100"))

    def test_kill_switch_denies_even_supplied_approval(self):
        broker = PaperBroker(replace(self.settings, risk=RiskLimits(kill_switch=True)), self.repository, self.session)
        with self.assertRaises(SimulationError):
            broker.open_position(signal(), self.approved, D("100"))

    def test_open_failure_rolls_back_database_and_memory(self):
        with patch.object(self.repository, "_insert_order", side_effect=sqlite3.IntegrityError("test")):
            with self.assertRaises(sqlite3.IntegrityError):
                self.broker.open_position(signal(), self.approved, D("100"))
        self.assertEqual(self.repository.records("positions", self.session), [])
        self.assertEqual(self.broker.snapshot().cash, D("1000"))
        self.assertEqual(self.broker.snapshot().positions, ())

    def test_close_failure_rolls_back_database_and_memory(self):
        order = self.broker.open_position(signal(), self.approved, D("100"))
        before = self.broker.snapshot()
        with patch.object(self.repository, "_insert_order", side_effect=sqlite3.IntegrityError("test")):
            with self.assertRaises(sqlite3.IntegrityError):
                self.broker.close_position(order.position_id, D("110"), NOW, "exit")
        self.assertEqual(self.broker.snapshot(), before)
        self.assertEqual(self.repository.records("positions", self.session)[0]["status"], "OPEN")
        self.assertEqual(self.repository.records("trades", self.session), [])

    def test_double_close_and_resume_rejected(self):
        order = self.broker.open_position(signal(), self.approved, D("100"))
        self.broker.close_position(order.position_id, D("110"), NOW, "exit")
        with self.assertRaises(SimulationError):
            self.broker.close_position(order.position_id, D("110"), NOW, "exit")
        with self.assertRaises(SimulationError):
            PaperBroker(self.settings, self.repository, self.session)

    def test_invalid_session_and_read_table_rejected(self):
        with self.assertRaises(SimulationError):
            PaperBroker(self.settings, self.repository, "missing")
        with self.assertRaises(ValueError):
            self.repository.records("sessions; DROP TABLE orders", self.session)
