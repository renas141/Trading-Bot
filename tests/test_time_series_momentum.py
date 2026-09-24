import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain import Direction
from app.market_data.models import Candle
from app.strategies.time_series_momentum import (
    TimeSeriesMomentumParameters,
    TimeSeriesMomentumStrategy,
)


D = Decimal
NOW = datetime(2023, 1, 1, tzinfo=timezone.utc)


def history(count=721, *, falling=False):
    rows = []
    for index in range(count):
        level = D("1000") - D(index) if falling else D("100") + D(index)
        rows.append(Candle("BTC/USD", "4h", NOW + timedelta(hours=4 * index),
                           level, level + D("2"), level - D("2"), level, D("1")))
    return tuple(rows)


class TimeSeriesMomentumTests(unittest.TestCase):
    def test_agreeing_positive_horizons_enter_long_without_target(self):
        signal = TimeSeriesMomentumStrategy().analyze(history())
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertLess(signal.stop_price, history()[-1].close)
        self.assertIsNone(signal.take_profit_price)
        self.assertEqual(signal.requested_leverage, D("10"))

    def test_agreeing_negative_horizons_enter_short(self):
        rows = history(falling=True)
        signal = TimeSeriesMomentumStrategy().analyze(rows)
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertGreater(signal.stop_price, rows[-1].close)

    def test_disagreement_holds_and_warmup_is_explicit(self):
        rows = list(history())
        rows[-181] = replace(rows[-181], open=D("900"), close=D("900"),
                             high=D("902"), low=D("898"))
        # Current is above the 120-day base but below this altered 30-day base.
        signal = TimeSeriesMomentumStrategy().analyze(tuple(rows))
        self.assertEqual(signal.direction, Direction.HOLD)
        warmup = TimeSeriesMomentumStrategy().analyze(tuple(rows[:720]))
        self.assertEqual(warmup.direction, Direction.HOLD)
        self.assertIn("Warm-up", warmup.reasons[0])

    def test_invalid_parameters_and_mixed_market_are_rejected(self):
        for values in ({"fast_momentum_bars": 1}, {"slow_momentum_bars": True},
                       {"fast_momentum_bars": 720}, {"stop_atr_multiple": D("NaN")},
                       {"requested_leverage": D("11")}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                TimeSeriesMomentumParameters(**values)
        rows = history()
        with self.assertRaises(ValueError):
            TimeSeriesMomentumStrategy().analyze(
                rows[:-1] + (replace(rows[-1], symbol="ETH/USD"),),
            )


if __name__ == "__main__":
    unittest.main()
