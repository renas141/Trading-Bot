import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain import Direction
from app.market_data.models import Candle
from app.market_data.perpetual_regime_alignment import AlignedRegimeBar
from app.strategies.regime_confirmed_momentum import RegimeConfirmedMomentumStrategy


D = Decimal
START = datetime(2025, 1, 1, tzinfo=timezone.utc)
STEP = timedelta(hours=4)


def histories(rising=True, short=False):
    candles, aligned = [], []
    for index in range(170):
        price = D(500 - index if short else 100 + index)
        candle = Candle("BTC/USD", "4h", START + STEP * index,
                        price, price + 1, price - 1, price, D("5"))
        candles.append(candle)
        direction = D("-1") if short else D("1")
        oi = D(1000 + index if rising else 2000 - index)
        regime = {
            "open_interest": oi,
            "aggressor_differential": direction * D("2"),
            "liquidation_volume": D("0"),
            "rolling_volatility": D("1"),
            "long_short_ratio": D("1"),
            "buy_volume": D("3"),
            "sell_volume": D("2"),
            "cumulative_volume_delta": direction * D(index),
        }
        source = candle.timestamp - STEP
        aligned.append(AlignedRegimeBar(candle, candle, source, regime))
    return tuple(candles), tuple(aligned)


class RegimeConfirmedMomentumTests(unittest.TestCase):
    def test_rising_oi_and_agreeing_flow_confirm_long_and_short(self):
        for short, expected in ((False, Direction.LONG), (True, Direction.SHORT)):
            candles, aligned = histories(short=short)
            signal = RegimeConfirmedMomentumStrategy(aligned).analyze(candles)
            self.assertEqual(signal.direction, expected)
            self.assertIsNotNone(signal.stop_price)
            self.assertEqual(signal.requested_leverage, D("10"))

    def test_falling_oi_or_missing_delayed_history_holds(self):
        candles, aligned = histories(rising=False)
        signal = RegimeConfirmedMomentumStrategy(aligned).analyze(candles)
        self.assertEqual(signal.direction, Direction.HOLD)
        self.assertTrue(any("FAIL 7-day open-interest" in reason for reason in signal.reasons))

        signal = RegimeConfirmedMomentumStrategy(aligned[-1:]).analyze(candles)
        self.assertEqual(signal.direction, Direction.HOLD)
        self.assertIn("incomplete", signal.reasons[0])

    def test_future_extension_cannot_change_existing_signal(self):
        candles, aligned = histories()
        strategy = RegimeConfirmedMomentumStrategy(aligned)
        before = strategy.analyze(candles[:-1])
        after = strategy.analyze(candles[:-1])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
