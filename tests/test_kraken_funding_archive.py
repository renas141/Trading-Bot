import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.errors import MarketDataError
from app.market_data.kraken_funding_archive import download, load_dataset, public_get


START = datetime(2026, 9, 23, tzinfo=timezone.utc)
END = START + timedelta(hours=4)


def payload(hours=4):
    stamps = [int((START + timedelta(hours=index)).timestamp() * 1000)
              for index in range(hours)]
    rates = [["0", "0", "0", str(index / 100000)] for index in range(hours)]
    return json.dumps({"result": {"timestamp": stamps,
                                  "data": {"rate": rates, "relativeRate": rates},
                                  "more": False}, "errors": []}).encode()


class KrakenFundingArchiveTests(unittest.TestCase):
    def test_download_and_verified_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "funding"
            quality = download(target, START, END, transport=lambda url: payload(),
                               clock=lambda: END + timedelta(hours=1))
            self.assertEqual(quality["rows"], 4)
            points, manifest = load_dataset(target)
            self.assertEqual(len(points), 4)
            self.assertEqual(manifest["source"]["field"], "relativeRate close")
            (target / "funding.csv").write_text("changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_dataset(target)

    def test_missing_hour_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "funding"
            with self.assertRaisesRegex(ValueError, "missing"):
                download(target, START, END, transport=lambda url: payload(3),
                         clock=lambda: END + timedelta(hours=1))
            self.assertFalse(target.exists())

    def test_foreign_url_and_future_range_are_rejected_before_network(self):
        with self.assertRaises(MarketDataError):
            public_get("https://example.com/funding?since=1&to=2&interval=3600")
        calls = []
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            download(Path(directory) / "future", START, END,
                     transport=lambda url: calls.append(url), clock=lambda: START)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
