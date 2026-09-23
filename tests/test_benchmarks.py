import unittest
from dataclasses import replace

from app.config.settings import Settings
from app.domain import TradingMode
from backtesting.benchmarks import benchmarks
from tests.helpers import D
from tests.test_strategy import trend_candles


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.candles = tuple(replace(c, open=price, high=price, low=price, close=price)
                             for c, price in zip(trend_candles(2), (D("100"), D("110"))))
        self.settings = Settings(mode=TradingMode.BACKTEST, paper_fee_rate=D("0"), paper_slippage_bps=D("0"))

    def test_buy_hold_and_cash_have_known_cost_free_results(self):
        result = benchmarks(self.candles, self.settings)
        self.assertEqual(D(result["buy_hold"]["performance"]["net_profit"]), D("100"))
        self.assertEqual(D(result["buy_hold"]["performance"]["max_drawdown"]), 0)
        self.assertEqual(D(result["cash"]["performance"]["net_profit"]), 0)
        self.assertEqual(result["cash"]["performance"]["trades"], 0)

    def test_cash_rounding_and_both_fees_are_accounted(self):
        result = benchmarks(self.candles, replace(self.settings, quantity_step=D("1"), paper_fee_rate=D("0.01")))["buy_hold"]
        self.assertEqual(result["trade"]["position"]["quantity"], D("9"))
        self.assertEqual(result["uninvested_cash"], D("91"))
        self.assertEqual(D(result["performance"]["fees"]), D("18.9"))
        self.assertEqual(D(result["performance"]["net_profit"]), D("71.1"))
        self.assertEqual(D(result["performance"]["max_drawdown"]), D("0.018"))

    def test_flat_market_loses_round_trip_costs(self):
        candles = tuple(replace(c, open=D("100"), high=D("100"), low=D("100"), close=D("100")) for c in self.candles)
        result = benchmarks(candles, Settings(mode=TradingMode.BACKTEST, paper_spread_bps=D("10")))
        self.assertLess(D(result["buy_hold"]["performance"]["net_profit"]), 0)
        self.assertEqual(D(result["cash"]["performance"]["net_profit"]), 0)

    def test_benchmark_does_not_apply_strategy_drawdown_exit(self):
        candles = (self.candles[0], replace(self.candles[1], open=D("80"), high=D("80"), low=D("80"), close=D("80")))
        result = benchmarks(candles, self.settings)["buy_hold"]["performance"]
        self.assertEqual(D(result["max_drawdown"]), D("0.2"))
        self.assertEqual(D(result["net_profit"]), D("-200"))
