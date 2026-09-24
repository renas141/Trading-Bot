import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.errors import MarketDataError
from app.market_data.kraken_perpetual_regime_history import (
    INTERVAL,
    download,
    load_dataset,
    parse_page,
    public_get,
)


START = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(hours=12)


def payload(kind, stamps, *, more=False):
    if kind == "open-interest":
        data = [[str(100 + index), str(102 + index), str(99 + index), str(101 + index)]
                for index, _ in enumerate(stamps)]
    elif kind == "cvd":
        data = {"buy_volume": [str(3 + index) for index, _ in enumerate(stamps)],
                "sell_volume": [str(2 + index) for index, _ in enumerate(stamps)],
                "cvd": [str(10 + index) for index, _ in enumerate(stamps)]}
    else:
        base = {"aggressor-differential": -1, "liquidation-volume": 0,
                "rolling-volatility": 1.5, "long-short-ratio": 0.6}[kind]
        data = [base + index for index, _ in enumerate(stamps)]
    return json.dumps({"result": {"timestamp": stamps, "data": data, "more": more},
                       "errors": []}).encode()


class KrakenPerpetualRegimeHistoryTests(unittest.TestCase):
    def test_paginated_download_builds_verified_aligned_dataset(self):
        starts = []

        def transport(url):
            parsed = urlsplit(url)
            kind = parsed.path.rsplit("/", 1)[-1]
            since = int(parse_qs(parsed.query)["since"][0])
            starts.append((kind, since))
            first = int(START.timestamp())
            if since == first:
                return payload(kind, [first, first + INTERVAL], more=True)
            return payload(kind, [first + 2 * INTERVAL])

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "dataset"
            quality = download(target, START, END, transport=transport,
                               clock=lambda: END + timedelta(hours=1))
            self.assertTrue(quality["ready"])
            self.assertEqual(quality["rows"], 3)
            rows, manifest = load_dataset(target)
            self.assertEqual(len(rows), 3)
            self.assertEqual(str(rows[0]["open_interest"]), "101")
            self.assertEqual(str(rows[-1]["cumulative_volume_delta"]), "10")
            self.assertEqual(len(manifest["source"]["pages"]["cvd"]), 2)
            self.assertEqual(len(starts), 12)
            (target / "regime.csv").write_text("changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_dataset(target)

    def test_missing_interval_rejects_and_removes_partial_output(self):
        def transport(url):
            parsed = urlsplit(url)
            kind = parsed.path.rsplit("/", 1)[-1]
            first = int(START.timestamp())
            stamps = [first, first + INTERVAL, first + 2 * INTERVAL]
            if kind == "long-short-ratio":
                stamps.pop(1)
            return payload(kind, stamps)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "dataset"
            with self.assertRaisesRegex(ValueError, "missing"):
                download(target, START, END, transport=transport,
                         clock=lambda: END + timedelta(hours=1))
            self.assertFalse(target.exists())

    def test_malformed_pagination_and_unapproved_url_fail(self):
        first = int(START.timestamp())
        with self.assertRaises(MarketDataError):
            parse_page(payload("cvd", [first], more=True), "cvd", first, first + INTERVAL)
        with self.assertRaises(MarketDataError):
            public_get(
                "https://example.com/api/charts/v1/analytics/PF_XBTUSD/cvd"
                f"?since={first}&to={first + INTERVAL}&interval={INTERVAL}"
            )

    def test_future_or_unaligned_range_rejected_before_transport(self):
        calls = []
        transport = lambda url: calls.append(url)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                download(Path(directory) / "future", START, END, transport=transport,
                         clock=lambda: START)
            with self.assertRaises(ValueError):
                download(Path(directory) / "unaligned", START + timedelta(minutes=1), END,
                         transport=transport, clock=lambda: END + timedelta(hours=1))
        self.assertEqual(calls, [])

    def test_loader_reapplies_numeric_sign_constraints(self):
        first = int(START.timestamp())

        def transport(url):
            kind = urlsplit(url).path.rsplit("/", 1)[-1]
            return payload(kind, [first, first + INTERVAL, first + 2 * INTERVAL])

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "dataset"
            download(target, START, END, transport=transport,
                     clock=lambda: END + timedelta(hours=1))
            manifest_path = target / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            csv_path = target / "regime.csv"
            changed = csv_path.read_text().replace(",101,", ",-101,", 1)
            csv_path.write_text(changed)
            import hashlib
            manifest["sha256"]["regime.csv"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "Invalid open_interest"):
                load_dataset(target)


if __name__ == "__main__":
    unittest.main()
