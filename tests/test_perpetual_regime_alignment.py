import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.market_data.kraken_perpetual_regime_history import FIELDS
from app.market_data.models import Candle
from app.market_data.perpetual_regime_alignment import align_futures_regime


D = Decimal
START = datetime(2025, 1, 1, tzinfo=timezone.utc)
STEP = timedelta(hours=4)


def candle(index, *, timestamp=None):
    at = timestamp if timestamp is not None else START + STEP * index
    return Candle("BTC/USD", "4h", at, D("100"), D("102"), D("99"), D("101"), D("5"))


def regime(index):
    values = {name: D("1") for name in FIELDS}
    return {"timestamp": START + STEP * index, **values}


class PerpetualRegimeAlignmentTests(unittest.TestCase):
    def test_uses_previous_completed_bucket_with_full_bar_delay(self):
        trade = tuple(candle(index) for index in range(4))
        mark = tuple(candle(index) for index in range(4))
        rows = tuple(regime(index) for index in range(3))

        aligned = align_futures_regime(trade, mark, rows)

        self.assertEqual(len(aligned), 3)
        self.assertEqual(aligned[0].trade.timestamp, START + STEP)
        self.assertEqual(aligned[0].regime_timestamp, START)
        self.assertEqual(aligned[0].regime_completed_at, aligned[0].trade.timestamp)
        self.assertEqual(aligned[0].decision_at, START + STEP * 2)

    def test_rejects_price_or_regime_gap(self):
        trade = (candle(0), candle(2))
        with self.assertRaisesRegex(ValueError, "continuous"):
            align_futures_regime(trade, trade, (regime(0), regime(1)))

        trade = tuple(candle(index) for index in range(4))
        with self.assertRaisesRegex(ValueError, "continuous"):
            align_futures_regime(trade, trade, (regime(0), regime(2)))

    def test_rejects_unverified_values_and_misaligned_mark(self):
        trade = tuple(candle(index) for index in range(3))
        mark = (candle(0), candle(1), candle(3))
        with self.assertRaisesRegex(ValueError, "not aligned"):
            align_futures_regime(trade, mark, (regime(0), regime(1)))

        bad = regime(0)
        bad["open_interest"] = 1.0
        with self.assertRaisesRegex(ValueError, "verified decimals"):
            align_futures_regime(trade, trade, (bad, regime(1)))


if __name__ == "__main__":
    unittest.main()
