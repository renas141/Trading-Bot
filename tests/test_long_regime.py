import unittest
from datetime import datetime, timezone
from decimal import Decimal

from app.domain import Direction
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.long_regime import LongOnlyRegimeStrategy, UncappedLongOnlyRegimeStrategy
from app.strategies.models import Signal


class ShortFixture(Strategy):
    parameters = object()

    def analyze(self, history):
        return Signal("BTC/USD", history[-1].closed_at, Direction.SHORT, Decimal("1"),
                      ("fixture",), "fixture", "1", Decimal("110"), Decimal("80"), Decimal("10"))


class LongFixture(Strategy):
    parameters = object()

    def analyze(self, history):
        return Signal("BTC/USD", history[-1].closed_at, Direction.LONG, Decimal("1"),
                      ("fixture",), "fixture", "1", Decimal("90"), Decimal("120"), Decimal("10"))


class LongOnlyRegimeTests(unittest.TestCase):
    def test_short_is_suppressed_without_executable_prices(self):
        candle = Candle("BTC/USD", "4h", datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1"))
        signal = LongOnlyRegimeStrategy(ShortFixture()).analyze((candle,))
        self.assertEqual(signal.direction, Direction.HOLD)
        self.assertIsNone(signal.stop_price)
        self.assertIsNone(signal.take_profit_price)
        self.assertIn("SHORT suppressed", signal.reasons[-1])

    def test_uncapped_variant_keeps_entry_and_stop_but_removes_target(self):
        candle = Candle("BTC/USD", "4h", datetime(2024, 1, 1, tzinfo=timezone.utc),
                        Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1"))
        signal = UncappedLongOnlyRegimeStrategy(LongFixture()).analyze((candle,))
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.stop_price, Decimal("90"))
        self.assertIsNone(signal.take_profit_price)
        self.assertIn("trailing policy", signal.reasons[-1])


if __name__ == "__main__":
    unittest.main()
