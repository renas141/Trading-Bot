import copy
import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.market_data.datasets import save_dataset
from backtesting.diagnostics import decompose, diagnose, digest, exit_reference
from backtesting.research import research
from tests.helpers import D, NOW
from tests.test_strategy import trend_candles


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.assumptions = {"execution_model": "cash-long-next-bar-v1", "price_tick": "0.01",
                            "costs": {"fee_rate": "0.0026", "slippage_bps": "5", "spread_bps": "10"}}
        self.trade = {"id": "trade", "position": {"direction": "LONG", "leverage": "1", "quantity": "1",
                      "entry_price": "100.10", "entry_fee": "0.260260", "opened_at": NOW.isoformat(),
                      "stop_price": "99", "take_profit_price": "100.5"}, "exit_price": "100.89",
                      "exit_fee": "0.262314", "closed_at": (NOW + timedelta(minutes=30)).isoformat(),
                      "exit_reason": "END_OF_DATA"}

    def test_costs_reconcile_to_independently_calculated_net(self):
        result = decompose(self.trade, D("100"), D("101"), self.assumptions)
        self.assertEqual(result["reference_gross_eur"], D("1"))
        self.assertEqual(result["spread_eur"], D("0.1005"))
        self.assertEqual(result["slippage_eur"], D("0.1005"))
        self.assertEqual(result["rounding_eur"], D("0.009"))
        self.assertEqual(result["fees_eur"], D("0.522574"))
        self.assertEqual(result["net_eur"], D("0.267426"))
        self.assertEqual(result["holding_minutes"], D("30"))

    def test_target_above_entry_can_still_lose_net(self):
        result = decompose(self.trade, D("100"), D("101"), self.assumptions)
        self.assertEqual(result["target_net_at_entry_eur"], D("-0.231274"))
        self.assertLess(result["net_reward_risk_at_entry"], 0)
        self.trade.update(exit_reason="TAKE_PROFIT", exit_price="100.39", exit_fee="0.261014")
        result = decompose(self.trade, D("100"), D("100.5"), self.assumptions)
        self.assertGreater(result["reference_gross_eur"], 0)
        self.assertEqual(result["net_eur"], D("-0.231274"))

    def test_corrupt_fills_fees_and_unsupported_models_fail_closed(self):
        for field, value in (("exit_price", "100.90"), ("exit_fee", "0.26")):
            trade = copy.deepcopy(self.trade)
            trade[field] = value
            with self.assertRaises(ValueError):
                decompose(trade, D("100"), D("101"), self.assumptions)
        self.assumptions["execution_model"] = "different-model"
        with self.assertRaises(ValueError):
            decompose(self.trade, D("100"), D("101"), self.assumptions)

    def test_gap_exit_uses_open_for_stop_but_caps_target(self):
        bar = SimpleNamespace(open=D("98"), close=D("100"))
        for reason, expected in (("STOP_GAP", "98"), ("STOP_LOSS", "99"),
                                 ("STOP_FIRST_AMBIGUOUS_BAR", "99"), ("END_OF_DATA", "100"),
                                 ("TAKE_PROFIT", "100.5"), ("TAKE_PROFIT_GAP", "100.5")):
            with self.subTest(reason=reason):
                self.trade["exit_reason"] = reason
                self.assertEqual(exit_reference(self.trade, bar), D(expected))
        self.trade["exit_reason"] = "UNKNOWN"
        with self.assertRaises(ValueError):
            exit_reference(self.trade, bar)


class DiagnosisIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        candles = trend_candles(80)
        save_dataset(self.root / "dataset", candles, symbol="BTC/EUR", timeframe="15m", start=NOW,
                     end=candles[-1].closed_at, raw=b"diagnostic fixture", source={"format": "fixture"},
                     captured_at=NOW + timedelta(days=2))
        with patch("builtins.print"):
            research(self.root / "dataset", candles[60].timestamp, self.root / "research")

    def test_empty_trades_generate_valid_report_and_never_change_sources(self):
        sources = list((self.root / "research").iterdir())
        before = {p.name: digest(p) for p in sources}
        report = diagnose(self.root / "research", self.root / "dataset", self.root / "diagnosis")
        self.assertEqual(len(report["runs"]), 4)
        self.assertTrue(all(r["trades"] == 0 and r["net_eur"] == 0 for r in report["runs"]))
        self.assertEqual({p.name: digest(p) for p in sources}, before)
        with (self.root / "diagnosis/trades.csv").open() as file:
            reader = csv.DictReader(file)
            self.assertIn("entry_reasons", reader.fieldnames)
            self.assertEqual(list(reader), [])
        saved = json.loads((self.root / "diagnosis/summary.json").read_text())
        self.assertEqual(saved["runs"][0]["net_eur"], "0")
        with self.assertRaises(FileExistsError):
            diagnose(self.root / "research", self.root / "dataset", self.root / "diagnosis")

    def test_changed_protocol_rejected_before_output(self):
        path = self.root / "research/protocol.json"
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "Protocol hash"):
            diagnose(self.root / "research", self.root / "dataset", self.root / "diagnosis")
        self.assertFalse((self.root / "diagnosis").exists())

    def test_inconsistent_database_result_rejected(self):
        with closing(sqlite3.connect(self.root / "research/research.sqlite3")) as db:
            db.execute("UPDATE backtest_results SET payload=json_set(payload,'$.performance.trades',100)")
            db.commit()
        with self.assertRaisesRegex(ValueError, "performance mismatch"):
            diagnose(self.root / "research", self.root / "dataset", self.root / "diagnosis")
        self.assertFalse((self.root / "diagnosis").exists())

    def test_executed_trade_is_joined_to_signal_and_exported(self):
        candles = list(trend_candles(80))
        candles[55] = replace(candles[55], open=D("109"), high=D("111"), low=D("108"), close=D("110"), volume=D("12"))
        candles[56] = replace(candles[56], open=D("110"), high=D("111"), low=D("109"), close=D("110"))
        candles[57] = replace(candles[57], open=D("110"), high=D("114"), low=D("109"), close=D("113"))
        save_dataset(self.root / "traded_dataset", candles, symbol="BTC/EUR", timeframe="15m", start=NOW,
                     end=candles[-1].closed_at, raw=b"traded fixture", source={"format": "fixture"},
                     captured_at=NOW + timedelta(days=2))
        with patch("builtins.print"):
            original = research(self.root / "traded_dataset", candles[60].timestamp, self.root / "traded_research")
        report = diagnose(self.root / "traded_research", self.root / "traded_dataset", self.root / "diagnosis")
        self.assertEqual(report["runs"][0]["trades"], 1)
        self.assertEqual(report["runs"][0]["target_exits"], 1)
        self.assertEqual(report["runs"][0]["net_eur"], D(original["runs"][0]["performance"]["net_profit"]))
        with (self.root / "diagnosis/trades.csv").open() as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 2)
        self.assertIn("PASS Breakout", rows[0]["entry_reasons"])
        self.assertEqual(rows[0]["opened_at"], candles[56].timestamp.isoformat())
