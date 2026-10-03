import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain import Direction
from app.market_data.models import Candle
from app.market_data.perpetual_regime_alignment import AlignedRegimeBar
from app.strategies.funding_aware_regime_momentum import (
    FundingAwareRegimeMomentumStrategy,
)


D = Decimal
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
STEP = timedelta(hours=4)


def inputs(*, short=False, worsening_funding=False):
    candles, aligned, funding = [], [], {}
    for index in range(45):
        price = D(500 - index if short else 100 + index)
        candle = Candle("BTC/USD", "4h", START + STEP * index,
                        price, price + 1, price - 1, price, D("5"))
        candles.append(candle)
        direction = D("-1") if short else D("1")
        regime = {
            "open_interest": D(1000 + index),
            "aggressor_differential": direction * D("2"),
            "liquidation_volume": D("0"),
            "rolling_volatility": D("1"),
            "long_short_ratio": D("1"),
            "buy_volume": D("3"),
            "sell_volume": D("2"),
            "cumulative_volume_delta": direction * D(index),
        }
        aligned.append(AlignedRegimeBar(candle, candle, candle.timestamp - STEP, regime))
        funding[candle.timestamp] = D("-0.00002") if short else D("0.00002")
    if worsening_funding:
        funding[candles[-1].timestamp] = D("-0.00003") if short else D("0.00003")
    else:
        funding[candles[-1].timestamp] = D("-0.00001") if short else D("0.00001")
    return tuple(candles), tuple(aligned), funding


class FundingAwareRegimeMomentumTests(unittest.TestCase):
    def test_easing_directional_funding_confirms_long_and_short(self):
        for short, expected in ((False, Direction.LONG), (True, Direction.SHORT)):
            candles, aligned, funding = inputs(short=short)
            signal = FundingAwareRegimeMomentumStrategy(aligned, funding).analyze(candles)
            self.assertEqual(signal.direction, expected)
            self.assertIsNotNone(signal.stop_price)
            self.assertEqual(signal.requested_leverage, D("10"))
            self.assertTrue(any("PASS directional current funding" in reason
                                for reason in signal.reasons))

    def test_worsening_directional_funding_vetoes_entry(self):
        for short in (False, True):
            candles, aligned, funding = inputs(short=short, worsening_funding=True)
            signal = FundingAwareRegimeMomentumStrategy(aligned, funding).analyze(candles)
            self.assertEqual(signal.direction, Direction.HOLD)
            self.assertTrue(any("FAIL directional current funding" in reason
                                for reason in signal.reasons))

    def test_missing_funding_holds_and_future_data_cannot_change_signal(self):
        candles, aligned, funding = inputs()
        funding.pop(candles[-3].timestamp)
        strategy = FundingAwareRegimeMomentumStrategy(aligned, funding)
        signal = strategy.analyze(candles)
        self.assertEqual(signal.direction, Direction.HOLD)
        self.assertIn("incomplete", signal.reasons[0])

        candles, aligned, funding = inputs()
        strategy = FundingAwareRegimeMomentumStrategy(aligned, funding)
        before = strategy.analyze(candles[:-1])
        after = strategy.analyze(candles[:-1])
        self.assertEqual(before, after)

    def test_zero_open_interest_base_and_unaligned_funding_are_rejected_safely(self):
        candles, aligned, funding = inputs()
        changed = list(aligned)
        regime = dict(changed[2].regime)
        regime["open_interest"] = D("0")
        changed[2] = AlignedRegimeBar(changed[2].trade, changed[2].mark,
                                      changed[2].regime_timestamp, regime)
        signal = FundingAwareRegimeMomentumStrategy(changed, funding).analyze(candles)
        self.assertEqual(signal.direction, Direction.HOLD)
        self.assertIn("not positive", signal.reasons[0])

        bad_funding = dict(funding)
        bad_funding[START + timedelta(hours=1)] = D("0")
        with self.assertRaisesRegex(ValueError, "aware timestamps"):
            FundingAwareRegimeMomentumStrategy(aligned, bad_funding)


if __name__ == "__main__":
    unittest.main()
