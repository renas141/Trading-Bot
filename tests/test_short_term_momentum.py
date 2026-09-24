import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain import Direction
from app.market_data.models import Candle
from app.strategies.short_term_momentum import ShortTermMomentumStrategy


D = Decimal


def candles(count=169, *, rising=True):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        close = D("100") + (D(index) if rising else -D(index) / D("4"))
        rows.append(Candle("BTC/USD", "4h", start + timedelta(hours=4 * index),
                           close, close + 1, close - 1, close, D("10")))
    return rows


class ShortTermMomentumTests(unittest.TestCase):
    def test_fixed_horizons_and_long_signal(self):
        strategy = ShortTermMomentumStrategy()
        self.assertEqual(strategy.parameters.fast_momentum_bars, 42)
        self.assertEqual(strategy.parameters.slow_momentum_bars, 168)
        self.assertEqual(strategy.parameters.required_history, 169)
        signal = strategy.analyze(candles())
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertIsNone(signal.take_profit_price)
        self.assertEqual(signal.requested_leverage, D("10"))

    def test_fixed_horizons_and_short_signal(self):
        signal = ShortTermMomentumStrategy().analyze(candles(rising=False))
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertGreater(signal.stop_price, candles(rising=False)[-1].close)


if __name__ == "__main__":
    unittest.main()
