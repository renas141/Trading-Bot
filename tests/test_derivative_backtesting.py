import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.derivatives.settings import DerivativeSettings
from app.domain import Direction
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.models import Signal
from backtesting.derivatives import DerivativeBacktester, ProfitProtection


D = Decimal
NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def bar(index, opening="100", high="105", low="95", close="100"):
    return Candle("BTC/USD", "4h", NOW + timedelta(hours=4 * index),
                  D(opening), D(high), D(low), D(close), D("10"))


class ScriptedDerivativeStrategy(Strategy):
    def __init__(self, stop="90", target="110"):
        self.stop, self.target = D(stop), D(target)

    def analyze(self, history):
        enter = len(history) == 1
        return Signal("BTC/USD", history[-1].closed_at,
                      Direction.LONG if enter else Direction.HOLD,
                      D("1") if enter else D("0"), ("Scripted derivative event",),
                      "test", "1", self.stop if enter else None,
                      self.target if enter else None, D("10"))


class DerivativeBacktestingTests(unittest.TestCase):
    def setUp(self):
        self.settings = DerivativeSettings(fee_rate=D("0"), slippage_bps=D("0"))

    def test_signal_executes_next_open_and_target_closes(self):
        candles = (bar(0), bar(1, high="111", low="95", close="108"))
        result = DerivativeBacktester(ScriptedDerivativeStrategy(), self.settings, D("0")).run(candles, candles)
        self.assertEqual(result.entries, 1)
        self.assertEqual(result.performance.trades, 1)
        self.assertEqual(result.performance.net_profit, D("10"))
        self.assertEqual(result.performance.maximum_leverage_used, 1)

    def test_mark_price_can_liquidate_when_trade_price_does_not_hit_stop(self):
        settings = replace(self.settings, max_margin_fraction=D("0.01"))
        trades = (bar(0), bar(1, high="101", low="98", close="99"))
        marks = (bar(0), bar(1, high="101", low="94", close="99"))
        result = DerivativeBacktester(
            ScriptedDerivativeStrategy(stop="97", target="106"), settings, D("0")
        ).run(trades, marks)
        self.assertEqual(result.performance.maximum_leverage_used, 10)
        self.assertEqual(result.performance.liquidations, 1)
        self.assertLess(result.performance.net_profit, D("0"))

    def test_adverse_funding_is_charged_to_short_and_long_sensitivities(self):
        candles = (bar(0), bar(1, high="105", low="95", close="100"),
                   bar(2, high="105", low="95", close="100"))
        result = DerivativeBacktester(
            ScriptedDerivativeStrategy(stop="90", target="120"), self.settings, D("0.001")
        ).run(candles, candles)
        self.assertGreater(result.performance.funding_paid, D("0"))
        self.assertEqual(result.performance.net_profit, -result.performance.funding_paid)

    def test_close_confirmed_break_even_is_effective_next_bar(self):
        candles = (bar(0), bar(1, high="112", low="95", close="111"),
                   bar(2, opening="99", high="102", low="95", close="100"))
        result = DerivativeBacktester(
            ScriptedDerivativeStrategy(stop="90", target="130"), self.settings, D("0"),
            ProfitProtection(D("1"), D("0")),
        ).run(candles, candles)
        self.assertEqual(result.stop_updates, 1)
        self.assertEqual(result.trades[0].position.stop_price, D("100"))
        self.assertEqual(result.trades[0].exit_reason, "STOP_GAP")
        self.assertEqual(result.performance.net_profit, D("-1"))

    def test_management_cannot_use_close_before_same_bar_stop(self):
        candles = (bar(0), bar(1, high="112", low="89", close="111"), bar(2))
        result = DerivativeBacktester(
            ScriptedDerivativeStrategy(stop="90", target="130"), self.settings, D("0"),
            ProfitProtection(D("1"), D("0")),
        ).run(candles, candles)
        self.assertEqual(result.stop_updates, 0)
        self.assertEqual(result.trades[0].exit_reason, "STOP_LOSS")
        self.assertEqual(result.performance.net_profit, D("-10"))


if __name__ == "__main__":
    unittest.main()
