import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from app.config.settings import Settings
from app.database.repository import Repository
from app.domain import Direction, TradingMode
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import PaperBroker
from app.market_data.models import Candle
from app.risk.stop_risk import StopRiskManager
from app.strategies.no_trade import NoTradeStrategy
from app.strategies.models import Signal
from backtesting.execution import BacktestExecution
from backtesting.observed_history import GAP_REJECTION, ObservedHistoryBacktester, VerifiedEmptyInterval, validate_observed_history
from tests.helpers import D, NOW


def bar(hour, price="100"):
    return Candle("BTC/EUR", "4h", NOW + timedelta(hours=hour), *([D(price)] * 4), D(1))


class ObservedHistoryTests(unittest.TestCase):
    def test_undeclared_extra_or_misaligned_gaps_fail_before_execution(self):
        candles = (bar(0), bar(8))
        gap = VerifiedEmptyInterval(NOW + timedelta(hours=4), NOW + timedelta(hours=8), NOW + timedelta(hours=9), "a" * 64)
        validate_observed_history(candles, (gap,))
        for gaps in ((), (gap, gap), (replace(gap, first_observation_at=NOW + timedelta(hours=12)),)):
            execution = Mock()
            with self.assertRaises(ValueError):
                ObservedHistoryBacktester(NoTradeStrategy(), execution).run(candles, gaps)
            execution.on_bar.assert_not_called()

    def test_open_position_survives_pause_and_stops_at_first_known_trade(self):
        candles = (bar(0), bar(4), bar(12, "80"), bar(16, "82"))
        gap = VerifiedEmptyInterval(NOW + timedelta(hours=8), NOW + timedelta(hours=12), NOW + timedelta(hours=13), "a" * 64)
        seen = []
        strategy = Mock()
        def analyze(history):
            seen.append(tuple(history))
            current = history[-1]
            if current.timestamp in (NOW, NOW + timedelta(hours=4)):
                return Signal("BTC/EUR", current.closed_at, Direction.LONG, D(1), ("fixture",), "fixture", "1",
                              stop_price=D(90), take_profit_price=D(120))
            return NoTradeStrategy().analyze(history)
        strategy.analyze.side_effect = analyze
        settings = Settings(mode=TradingMode.BACKTEST, timeframe="4h", paper_fee_rate=D(0), paper_spread_bps=D(0), paper_slippage_bps=D(0))
        with tempfile.TemporaryDirectory() as directory, Repository(Path(directory) / "test.db") as repo:
            session = repo.start_session(settings.mode, settings.initial_capital, settings.symbol)
            broker = PaperBroker(settings, repo, session)
            execution = BacktestExecution(OrderManager(StopRiskManager(settings), broker, repo, session), broker, repo, session)
            result = ObservedHistoryBacktester(strategy, execution).run(candles, (gap,))
            self.assertEqual(result.performance.trades, 1)
            closed = broker.trades[0]
            self.assertEqual(closed.exit_reason, "STOP_GAP")
            self.assertEqual(closed.closed_at, gap.first_observation_at)
            self.assertEqual(closed.exit_price, D(80))
            self.assertEqual(result.performance.net_profit, D(-20))
            self.assertEqual([len(history) for history in seen], [1, 2, 1, 2])
            self.assertEqual(seen[2], (candles[2],))
            signals = repo.records("signals", session)
            expired = [r for r in signals if GAP_REJECTION in json.loads(r["risk_decision"])["reasons"]]
            self.assertEqual(len(expired), 1)
            marks = repo.records("equity", session)
            for row in marks:
                self.assertFalse(gap.start.isoformat() <= row["timestamp"] < gap.first_observation_at.isoformat())

    def test_observed_open_time_is_validated_before_any_mark(self):
        execution = object.__new__(BacktestExecution)
        execution._finished = False
        execution._record_equity = Mock()
        with self.assertRaises(ValueError):
            execution.on_bar(bar(0), None, observed_open_at=NOW + timedelta(hours=4))
        execution._record_equity.assert_not_called()
