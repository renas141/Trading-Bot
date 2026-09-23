import unittest
from dataclasses import replace

from app.domain import Direction
from app.market_data.models import Candle
from app.portfolio.models import Position, Trade
from app.risk.exits import ExitPlan
from tests.helpers import D, NOW, signal


class ModelTests(unittest.TestCase):
    def test_candle_invariants(self):
        valid = Candle("BTC/EUR", "15m", NOW, D("100"), D("110"), D("90"), D("105"), D("0"))
        for changes in ({"high": D("99")}, {"low": D("106")}, {"close": D("NaN")},
                        {"volume": D("-1")}, {"timestamp": NOW.replace(tzinfo=None)},
                        {"timeframe": "2m"}, {"symbol": "BTC"}, {"open": 100.0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(valid, **changes)
        self.assertEqual((valid.closed_at - NOW).total_seconds(), 900)

    def test_signals_require_explanations_and_bounded_confidence(self):
        for changes in ({"confidence": D("1.01")}, {"reasons": ()}, {"reasons": ["mutable"]},
                        {"strategy_version": ""}, {"direction": "LONG"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(signal(), **changes)

    def test_long_and_short_pnl_model(self):
        for direction, expected in ((Direction.LONG, D("16")), (Direction.SHORT, D("-24"))):
            position = Position("p", "BTC/EUR", direction, D("2"), D("100"), NOW, D("2"))
            trade = Trade("t", position, D("110"), NOW, D("2"), "test exit")
            self.assertEqual(trade.net_pnl, expected)
            self.assertEqual(trade.fees, D("4"))

    def test_exit_plan_requires_valid_fractions_and_reasons(self):
        with self.assertRaises(ValueError):
            ExitPlan(close_fraction=D("1.1"), reasons=("test",))
        with self.assertRaises(ValueError):
            ExitPlan(stop_price=D("90"))
