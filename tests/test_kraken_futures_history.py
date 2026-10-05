import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.errors import MarketDataError
from app.market_data.kraken_futures import load_futures_dataset
from app.market_data.kraken_futures_history import download, public_get


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
STEP = timedelta(hours=4)


def payload(start, count, more):
    rows = []
    for offset in range(count):
        stamp = start + STEP * offset
        rows.append({
            "time": int(stamp.timestamp() * 1000), "open": "100", "high": "102",
            "low": "99", "close": "101", "volume": "5",
        })
    return json.dumps({"candles": rows, "more_candles": more}).encode()


class KrakenFuturesHistoryTests(unittest.TestCase):
    def test_public_transport_rejects_wrong_host_and_unaligned_range(self):
        with self.assertRaises(MarketDataError):
            public_get("https://example.com/api/charts/v1/trade/PF_XBTUSD/4h?from=1&to=2")
        with self.assertRaises(MarketDataError):
            public_get("https://futures.kraken.com/api/charts/v1/trade/PF_XBTUSD/4h?from=1&to=14401")

    def test_download_paginates_and_builds_verified_trade_and_mark_dataset(self):
        calls = []

        def transport(url):
            calls.append(url)
            query = parse_qs(urlsplit(url).query)
            cursor = datetime.fromtimestamp(int(query["from"][0]), timezone.utc)
            return payload(cursor, 2 if cursor == START else 1, cursor == START)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "history"
            quality = download(
                output, START, START + STEP * 3, transport,
                clock=lambda: START + timedelta(days=2),
            )
            trade, mark, manifest = load_futures_dataset(output)
            self.assertTrue(quality["ready"])
            self.assertEqual(len(trade), 3)
            self.assertEqual(len(mark), 3)
            self.assertEqual(len(calls), 4)
            self.assertEqual(len(manifest["source"]["pages"]["trade"]), 2)
            self.assertIn("seen development", manifest["source"]["purpose"])


if __name__ == "__main__":
    unittest.main()
