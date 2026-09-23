import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain import Direction
from app.market_data.models import Candle
from app.strategies.donchian_trend import DonchianTrendParameters, DonchianTrendStrategy


D = Decimal
NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def rising_history(count=631):
    rows = []
    for index in range(count):
        close = D("100") + D(index) / D("10")
        rows.append(Candle("BTC/USD", "4h", NOW + timedelta(hours=4 * index),
                           close, close + D("0.2"), close - D("0.2"), close, D("1")))
    return tuple(rows)


class DonchianTrendTests(unittest.TestCase):
    def test_confirmed_breakout_has_stop_and_no_fixed_target(self):
        history = rising_history()
        current = replace(history[-1], high=D("170"), close=D("170"))
        signal = DonchianTrendStrategy().analyze(history[:-1] + (current,))
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertIsNotNone(signal.stop_price)
        self.assertIsNone(signal.take_profit_price)
        self.assertEqual(signal.requested_leverage, D("10"))

    def test_breakout_uses_only_prior_highs(self):
        history = rising_history()
        current = replace(history[-1], high=D("1000"), close=D("170"))
        self.assertEqual(DonchianTrendStrategy().analyze(history[:-1] + (current,)).direction,
                         Direction.LONG)

    def test_invalid_parameters_and_mixed_markets_are_rejected(self):
        for values in ({"trend_period": 1}, {"atr_period": True},
                       {"stop_atr_multiple": D("NaN")}, {"requested_leverage": D("11")}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                DonchianTrendParameters(**values)
        history = rising_history()
        with self.assertRaises(ValueError):
            DonchianTrendStrategy().analyze(history[:-1] + (replace(history[-1], symbol="ETH/USD"),))


if __name__ == "__main__":
    unittest.main()
