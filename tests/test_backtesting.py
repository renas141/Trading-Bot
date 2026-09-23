import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from app.market_data.candles import load_candles
from app.market_data.models import Candle
from app.strategies.no_trade import NoTradeStrategy
from backtesting.engine import Backtester
from tests.helpers import D, NOW


class BacktestingTests(unittest.TestCase):
    def setUp(self):
        self.candles = tuple(Candle("BTC/EUR", "15m", NOW + timedelta(minutes=15 * i),
                                    D("100"), D("110"), D("90"), D("105"), D("2")) for i in range(3))

    def test_strategy_sees_only_closed_prefix(self):
        seen = []
        strategy = Mock()
        strategy.analyze.side_effect = lambda history: (seen.append(history), NoTradeStrategy().analyze(history))[1]
        execution = Mock()
        execution.broker.settings.initial_capital = D("1000")
        execution.broker.snapshot.return_value.cash = D("1000")
        execution.broker.trades = []
        execution.broker.total_fees = D("0")
        execution.equity_curve = [D("1000")]
        result = Backtester(strategy, execution).run(self.candles)
        self.assertEqual([len(history) for history in seen], [1, 2, 3])
        self.assertEqual(tuple(seen[0]), self.candles[:1])
        self.assertEqual(result.candles_processed, 3)
        self.assertEqual(execution.on_bar.call_count, 3)
        self.assertIsNone(execution.on_bar.call_args_list[0].args[1])
        self.assertEqual(execution.on_bar.call_args_list[1].args[1].timestamp, self.candles[0].closed_at)
        execution.record_unexecuted.assert_called_once()

    def test_invalid_input_produces_no_output(self):
        cases = [(), self.candles[::-1], (self.candles[0], self.candles[0]),
                 (self.candles[0], replace(self.candles[1], symbol="ETH/EUR")),
                 (self.candles[0], replace(self.candles[1], timestamp=NOW + timedelta(minutes=1)))]
        for candles in cases:
            execution = Mock()
            with self.subTest(candles=candles), self.assertRaises(ValueError):
                Backtester(NoTradeStrategy(), execution).run(candles)
            execution.on_bar.assert_not_called()

    def test_future_signal_rejected(self):
        strategy = Mock()
        strategy.analyze.return_value = replace(NoTradeStrategy().analyze(self.candles), timestamp=NOW + timedelta(days=1))
        with self.assertRaises(ValueError):
            Backtester(strategy, Mock()).run(self.candles)

    def test_csv_ingestion_and_bad_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.csv"
            path.write_text("timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,100,110,90,105,2\n")
            self.assertEqual(load_candles(path, "BTC/EUR", "15m"), self.candles[:1])
            path.write_text("timestamp,open,high,low,close,volume\n2024-01-01T00:00:00,100,110,90,105,2\n")
            with self.assertRaisesRegex(ValueError, "line 2"):
                load_candles(path, "BTC/EUR", "15m")
