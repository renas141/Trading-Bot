import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.market_data.kraken_funding import (
    align_hourly_funding_to_4h,
    parse_hourly_funding,
)


NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)


def payload(rates, *, more=False):
    return json.dumps({
        "result": {
            "timestamp": [int((NOW + timedelta(hours=i)).timestamp() * 1000)
                          for i in range(len(rates))],
            "data": {"rate": [["0", "0", "0", "0"] for _ in rates],
                     "relativeRate": [[str(rate)] * 4 for rate in rates]},
            "more": more,
        },
        "errors": [],
    }).encode()


class KrakenFundingTests(unittest.TestCase):
    def test_signed_hourly_rates_align_to_4h_sum(self):
        points = parse_hourly_funding(
            payload(("0.001", "-0.0005", "0.002", "0")), NOW, NOW + timedelta(hours=4)
        )
        self.assertEqual(align_hourly_funding_to_4h(points, (NOW,)),
                         (Decimal("0.0025"),))

    def test_partial_payload_is_rejected_by_default(self):
        with self.assertRaisesRegex(ValueError, "partial"):
            parse_hourly_funding(payload(("0.001",), more=True), NOW, NOW + timedelta(hours=1))

    def test_missing_hour_cannot_silently_become_zero(self):
        points = parse_hourly_funding(
            payload(("0.001", "0.001", "0.001")), NOW, NOW + timedelta(hours=4)
        )
        with self.assertRaisesRegex(ValueError, "Missing hourly funding"):
            align_hourly_funding_to_4h(points, (NOW,))


if __name__ == "__main__":
    unittest.main()
