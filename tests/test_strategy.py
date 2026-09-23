import unittest
from dataclasses import replace
from datetime import timedelta

from app.domain import Direction
from app.indicators.core import average_true_range
from app.market_data.models import Candle
from app.strategies.registry import make_strategy, strategy_metadata
from app.strategies.trend_breakout import TrendBreakoutParameters, TrendBreakoutStrategy
from backtesting.history import CandleHistory
from tests.helpers import D, NOW


def trend_candles(count=51):
    candles = []
    for index in range(count):
        close = D("100") + D(index) / 10
        candles.append(Candle("BTC/EUR", "15m", NOW + timedelta(minutes=15 * index),
                              close, close + D("0.1"), close - D("0.1"), close, D("10")))
    return tuple(candles)


class StrategyTests(unittest.TestCase):
    def setUp(self):
        candles = trend_candles()
        self.candles = candles[:-1] + (replace(candles[-1], open=D("109"), high=D("111"),
                                              low=D("108"), close=D("110"), volume=D("12")),)
        self.strategy = TrendBreakoutStrategy()

    def test_confirmed_breakout_proposes_atr_stop_and_explanations(self):
        result = self.strategy.analyze(self.candles)
        self.assertEqual(result.direction, Direction.LONG)
        self.assertEqual(result.confidence, D("1"))
        self.assertTrue(all(reason.startswith("PASS") for reason in result.reasons[:4]))
        self.assertEqual(result.stop_price, D("110") - 2 * average_true_range(self.candles, 14))
        self.assertEqual(result.take_profit_price, D("110") + 2 * (D("110") - result.stop_price))
        self.assertEqual(result.timestamp, self.candles[-1].closed_at)
        self.assertIn("not a calibrated", result.reasons[-1])

    def test_current_bar_excluded_from_breakout_and_volume_baselines(self):
        # Current close is below its own high, and current volume equals 1.2*prior mean.
        self.assertEqual(self.strategy.analyze(self.candles).direction, Direction.LONG)

    def test_volume_failure_keeps_signal_hold(self):
        candles = self.candles[:-1] + (replace(self.candles[-1], volume=D("11.99")),)
        result = self.strategy.analyze(candles)
        self.assertEqual(result.direction, Direction.HOLD)
        self.assertEqual(result.confidence, D("0.75"))
        self.assertIsNone(result.stop_price)
        self.assertTrue(result.reasons[3].startswith("FAIL"))

    def test_warmup_requires_closed_history(self):
        result = self.strategy.analyze(self.candles[:50])
        self.assertEqual(result.direction, Direction.HOLD)
        self.assertIn("50/51", result.reasons[0])

    def test_flat_market_and_zero_volume_do_not_trade(self):
        candles = tuple(replace(c, open=D("100"), high=D("100"), low=D("100"),
                                close=D("100"), volume=D("0")) for c in self.candles)
        result = self.strategy.analyze(candles)
        self.assertEqual(result.direction, Direction.HOLD)
        self.assertIn("No valid positive", result.reasons[-1])

    def test_invalid_parameters_and_mixed_market_rejected(self):
        for parameters in ({"trend_period": 0}, {"atr_period": True}, {"volume_multiplier": D("NaN")},
                           {"stop_atr_multiple": D("-1")}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                TrendBreakoutParameters(**parameters)
        with self.assertRaises(ValueError):
            self.strategy.analyze(self.candles[:-1] + (replace(self.candles[-1], symbol="ETH/EUR"),))

    def test_atr_includes_gaps_and_uses_simple_mean(self):
        candles = (Candle("BTC/EUR", "15m", NOW, D("100"), D("101"), D("99"), D("100"), D("1")),
                   Candle("BTC/EUR", "15m", NOW + timedelta(minutes=15), D("110"), D("112"), D("109"), D("111"), D("1")),
                   Candle("BTC/EUR", "15m", NOW + timedelta(minutes=30), D("110"), D("113"), D("108"), D("109"), D("1")))
        self.assertEqual(average_true_range(candles, 2), D("8.5"))

    def test_history_view_cannot_index_or_slice_future_candles(self):
        history = CandleHistory(self.candles, 3)
        self.assertEqual(tuple(history), self.candles[:3])
        self.assertEqual(history[-1], self.candles[2])
        self.assertEqual(history[:1000], self.candles[:3])
        self.assertEqual(history[::-1], self.candles[:3][::-1])
        for index in (3, -4):
            with self.assertRaises(IndexError):
                history[index]

    def test_future_extension_does_not_change_observed_signal(self):
        extension = trend_candles(80)
        history = CandleHistory(self.candles + extension[51:], 51)
        self.assertEqual(self.strategy.analyze(history), self.strategy.analyze(self.candles))

    def test_registry_keeps_no_trade_and_records_parameters(self):
        self.assertEqual(make_strategy("no_trade").analyze(self.candles).direction, Direction.HOLD)
        self.assertEqual(strategy_metadata("trend_breakout")["parameters"]["trend_period"], 50)
        with self.assertRaises(ValueError):
            make_strategy("unknown")
