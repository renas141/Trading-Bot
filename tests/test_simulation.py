import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from app.config.settings import Settings
from app.database.repository import Repository
from app.domain import Direction, TradingMode
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import PaperBroker
from app.market_data.models import Candle
from app.portfolio.models import Position, Trade
from app.risk.stop_risk import StopRiskManager
from app.strategies.base import Strategy
from app.strategies.models import Signal
from backtesting.engine import Backtester
from backtesting.execution import BacktestExecution
from backtesting.metrics import calculate_performance
from tests.helpers import D, NOW


def bar(index, opening="100", high="105", low="95", close="100"):
    return Candle("BTC/EUR", "15m", NOW + timedelta(minutes=15 * index),
                  D(opening), D(high), D(low), D(close), D("10"))


class ScriptedSignals(Strategy):
    """Test-only instructions, deliberately not an investment strategy."""

    def __init__(self, indices=(1,), stop="90", target=None):
        self.indices, self.stop, self.target = indices, stop, target

    def analyze(self, history):
        entry = len(history) in self.indices
        return Signal("BTC/EUR", history[-1].closed_at, Direction.LONG if entry else Direction.HOLD,
                      D("1") if entry else D("0"), ("Scripted unit-test event",), "test_fixture", "1",
                      stop_price=D(self.stop) if entry else None,
                      take_profit_price=D(self.target) if entry and self.target else None)


class SimulationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "test.db"
        self.repository = Repository(self.path)
        self.addCleanup(self.repository.connection.close)
        self.settings = Settings(mode=TradingMode.BACKTEST, paper_fee_rate=D("0"), paper_slippage_bps=D("0"))

    def simulate(self, candles, strategy=None, settings=None):
        settings = settings or self.settings
        self.session = self.repository.start_session(settings.mode, settings.initial_capital, settings.symbol)
        self.broker = PaperBroker(settings, self.repository, self.session)
        manager = OrderManager(StopRiskManager(settings), self.broker, self.repository, self.session)
        self.execution = BacktestExecution(manager, self.broker, self.repository, self.session)
        result = Backtester(strategy or ScriptedSignals(), self.execution).run(candles)
        return result

    def test_entry_at_next_open_not_signal_close(self):
        result = self.simulate((bar(0), bar(1, "110", "115", "105", "112")))
        trade = self.broker.trades[0]
        self.assertEqual(trade.position.entry_price, D("110"))
        self.assertEqual(trade.position.quantity, D("0.5"))
        self.assertEqual(trade.position.opened_at, NOW + timedelta(minutes=15))
        self.assertEqual(trade.exit_reason, "END_OF_DATA")
        self.assertEqual(result.performance.net_profit, D("1"))

    def test_stop_wins_when_stop_and_target_hit_same_bar(self):
        result = self.simulate((bar(0), bar(1, "100", "120", "80", "110")), ScriptedSignals(target="115"))
        self.assertEqual(self.broker.trades[0].exit_reason, "STOP_FIRST_AMBIGUOUS_BAR")
        self.assertEqual(self.broker.trades[0].exit_price, D("90"))
        self.assertEqual(result.performance.net_profit, D("-10"))
        self.assertEqual(result.performance.max_drawdown, D("0.01"))

    def test_target_exit(self):
        self.simulate((bar(0), bar(1, "100", "116", "95", "110")), ScriptedSignals(target="115"))
        self.assertEqual(self.broker.trades[0].exit_reason, "TAKE_PROFIT")
        self.assertEqual(self.broker.trades[0].net_pnl, D("15"))

    def test_gap_stop_uses_worse_open_and_latches_daily_limit(self):
        settings = replace(self.settings, risk=replace(self.settings.risk, max_daily_loss=D("0.015")))
        result = self.simulate((bar(0), bar(1), bar(2, "80", "85", "75", "80")),
                               ScriptedSignals(indices=(1, 2)), settings)
        self.assertEqual(len(self.broker.trades), 1)
        trade = self.broker.trades[0]
        self.assertEqual(trade.exit_reason, "STOP_GAP")
        self.assertEqual(trade.exit_price, D("80"))
        self.assertEqual(result.performance.net_profit, D("-20"))
        decisions = [json.loads(row["risk_decision"]) for row in self.repository.records("signals", self.session)]
        self.assertIn("Daily loss", decisions[1]["reasons"][0])

    def test_gap_target_does_not_assume_better_than_target_fill(self):
        self.simulate((bar(0), bar(1), bar(2, "120", "125", "119", "122")), ScriptedSignals(target="115"))
        self.assertEqual(self.broker.trades[0].exit_reason, "TAKE_PROFIT_GAP")
        self.assertEqual(self.broker.trades[0].exit_price, D("115"))

    def test_last_bar_loss_belongs_to_previous_utc_day(self):
        candles = (bar(0), bar(1, "100", "105", "85", "95"), bar(2))
        candles = tuple(replace(c, timestamp=c.timestamp + timedelta(hours=23, minutes=30)) for c in candles)
        settings = replace(self.settings, risk=replace(self.settings.risk, max_daily_loss=D("0.01")))
        self.simulate(candles, ScriptedSignals(indices=(1, 2)), settings)
        self.assertEqual(len(self.broker.trades), 2)
        self.assertEqual(self.broker.trades[0].closed_at.date(), NOW.date())
        self.assertEqual(self.broker.trades[1].position.opened_at, NOW + timedelta(days=1))

    def test_final_signal_not_filled_without_following_bar(self):
        result = self.simulate((bar(0),), ScriptedSignals())
        self.assertEqual(result.performance.trades, 0)
        self.assertEqual(self.repository.records("orders", self.session), [])
        decision = json.loads(self.repository.records("signals", self.session)[0]["risk_decision"])
        self.assertIn("No following candle", decision["reasons"][0])

    def test_gap_below_proposed_stop_rejects_new_entry(self):
        self.simulate((bar(0), bar(1, "80", "85", "75", "80")))
        self.assertEqual(self.broker.trades, [])

    def test_costs_reconcile_cash_trades_fees_and_database(self):
        settings = replace(self.settings, paper_fee_rate=D("0.0026"), paper_slippage_bps=D("5"), paper_spread_bps=D("10"))
        result = self.simulate((bar(0), bar(1, "100", "108", "95", "105")), settings=settings)
        self.assertEqual(result.performance.net_profit, sum(t.net_pnl for t in self.broker.trades))
        self.assertEqual(result.performance.fees, sum(t.fees for t in self.broker.trades))
        self.assertEqual(self.broker.snapshot().cash, D("1000") + result.performance.net_profit)
        self.assertEqual(self.broker.snapshot().positions, ())
        saved = json.loads(self.repository.records("positions", self.session)[0]["payload"])
        self.assertEqual(D(saved["stop_price"]), D("90"))
        self.assertEqual(len(self.repository.records("orders", self.session)), 2)

    def test_execution_session_cannot_be_reused(self):
        self.simulate((bar(0),))
        with self.assertRaises(ValueError):
            self.execution.on_bar(bar(1), None)

    def test_empty_trade_metrics_are_undefined_not_fabricated(self):
        metrics = calculate_performance(D("1000"), D("1000"), [], [D("1000")], D("0"))
        self.assertIsNone(metrics.win_rate)
        self.assertIsNone(metrics.profit_factor)
        self.assertIsNone(metrics.expectancy)

    def test_mixed_trade_statistics_use_net_pnl(self):
        long = Position("long", "BTC/EUR", Direction.LONG, D("1"), D("100"), NOW, D("1"))
        short = Position("short", "BTC/EUR", Direction.SHORT, D("1"), D("100"), NOW, D("1"))
        trades = [Trade("a", long, D("112"), NOW, D("1"), "test"),
                  Trade("b", short, D("103"), NOW, D("1"), "test")]
        metrics = calculate_performance(D("1000"), D("1005"), trades,
                                        [D("1000"), D("1010"), D("1005")], D("4"))
        self.assertEqual(metrics.net_profit, D("5"))
        self.assertEqual(metrics.win_rate, D("0.5"))
        self.assertEqual(metrics.profit_factor, D("2"))
        self.assertEqual(metrics.average_win, D("10"))
        self.assertEqual(metrics.average_loss, D("-5"))
        self.assertEqual(metrics.expectancy, D("2.5"))
        self.assertEqual((metrics.long_trades, metrics.short_trades), (1, 1))

    def test_database_v1_migration_preserves_prior_sessions(self):
        old_session = self.repository.start_session(TradingMode.PAPER, D("1000"), "BTC/EUR")
        self.repository.connection.execute("DROP TABLE backtest_results")
        self.repository.connection.execute("PRAGMA user_version=1")
        with Repository(self.path) as upgraded:
            self.assertEqual(upgraded.connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(upgraded.records("sessions", old_session)[0]["initial_capital"], "1000")
            self.assertEqual(upgraded.records("backtest_results", old_session), [])
