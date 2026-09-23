import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from app.cli import main
from app.market_data.datasets import save_dataset
from app.strategies.no_trade import NoTradeStrategy
from backtesting.engine import Backtester
from backtesting.research import research
from tests.helpers import D, NOW
from tests.test_strategy import trend_candles


class ResearchTests(unittest.TestCase):
    def test_warmup_is_observed_but_never_executed(self):
        candles = trend_candles(60)
        execution = Mock()
        execution.broker.settings.initial_capital = D("1000")
        execution.broker.snapshot.return_value.cash = D("1000")
        execution.broker.trades = []
        execution.broker.total_fees = D("0")
        execution.equity_curve = [D("1000")]
        strategy = Mock(wraps=NoTradeStrategy())
        Backtester(strategy, execution).run(candles[50:], warmup=candles[:50])
        self.assertEqual(execution.on_bar.call_count, 10)
        self.assertEqual(len(strategy.analyze.call_args_list[0].args[0]), 51)
        self.assertEqual(execution.on_bar.call_args_list[0].args[0], candles[50])
        self.assertIsNone(execution.on_bar.call_args_list[0].args[1])

    def test_overlapping_or_disconnected_warmup_rejected(self):
        candles = trend_candles(60)
        for warmup in (candles[:49], candles[:51]):
            execution = Mock()
            with self.assertRaises(ValueError):
                Backtester(NoTradeStrategy(), execution).run(candles[50:], warmup=warmup)
            execution.on_bar.assert_not_called()

    def test_research_saves_fixed_protocol_and_four_independent_runs(self):
        candles = trend_candles(80)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_dataset(root / "dataset", candles, symbol="BTC/EUR", timeframe="15m", start=NOW,
                         end=candles[-1].closed_at, raw=b"synthetic test fixture", source={"format": "fixture"},
                         captured_at=NOW + timedelta(days=2))
            with patch("builtins.print"):
                report = research(root / "dataset", candles[60].timestamp, root / "research")
            self.assertEqual(len(report["runs"]), 4)
            self.assertEqual(len({run["session_id"] for run in report["runs"]}), 4)
            protocol = json.loads((root / "research/protocol.json").read_text())
            self.assertEqual(protocol["holdout_warmup_rows"], 50)
            self.assertEqual(protocol["costs"]["double_costs"]["fee_rate"], "0.0052")
            with closing(sqlite3.connect(root / "research/research.sqlite3")) as database:
                self.assertEqual(database.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0], 4)
                self.assertEqual(database.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 160)
                self.assertEqual(database.execute("SELECT COUNT(*) FROM sessions WHERE status='STOPPED'").fetchone()[0], 4)
            with self.assertRaises(FileExistsError):
                research(root / "dataset", candles[60].timestamp, root / "research")

    def test_research_strategy_cannot_be_selected_in_paper_mode(self):
        with patch.dict(os.environ, {"TRADING_MODE": "PAPER"}, clear=True):
            self.assertEqual(main(["--env-file", "/nonexistent/trading.env", "--strategy", "trend_breakout"]), 1)
