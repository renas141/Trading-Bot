import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from app.errors import MarketDataError
from app.exchange.kraken import ENDPOINT, KrakenAdapter, public_get
from app.market_data.candles import load_candles
from app.market_data.cli import main as data_main
from app.market_data.datasets import load_dataset, save_dataset, split_dataset
from app.market_data.kraken_csv import parse_kraken_csv
from app.market_data.models import Candle
from app.market_data.quality import audit_candles
from backtesting.engine import Backtester
from tests.helpers import D, NOW


def candle(index=0):
    return Candle("BTC/EUR", "15m", NOW + timedelta(minutes=15 * index),
                  D("100"), D("110"), D("90"), D("105"), D("2.12345678"))


def response(rows=None):
    if rows is None:
        rows = [[int((NOW + timedelta(minutes=15 * i)).timestamp()),
                 "100", "110", "90", "105", "99", "2.12345678", 3] for i in range(4)]
    return json.dumps({"error": [], "result": {"XXBTZEUR": rows, "last": 1}}).encode()


class KrakenTests(unittest.TestCase):
    def adapter(self, raw):
        return KrakenAdapter(lambda _: raw, lambda: NOW + timedelta(minutes=45))

    def test_public_mapping_and_uncommitted_final_row_removed(self):
        transport = Mock(return_value=response())
        adapter = KrakenAdapter(transport, lambda: NOW + timedelta(minutes=45))
        result = adapter.download("BTC/EUR", "15m", NOW)
        self.assertEqual(result.candles, tuple(candle(i) for i in range(3)))
        self.assertEqual(result.raw, response())
        url = transport.call_args.args[0]
        self.assertTrue(url.startswith(ENDPOINT + "?"))
        self.assertIn("pair=XBTEUR", url)
        self.assertIn("interval=15", url)
        self.assertNotIn("private", url)

    def test_exclusive_end_and_inclusive_start(self):
        result = self.adapter(response()).download("BTC/EUR", "15m", NOW + timedelta(minutes=15),
                                                    NOW + timedelta(minutes=30))
        self.assertEqual(result.candles, (candle(1),))

    def test_final_row_removed_even_with_advanced_local_clock(self):
        adapter = KrakenAdapter(lambda _: response(), lambda: NOW + timedelta(days=1))
        self.assertEqual(len(adapter.fetch_candles("BTC/EUR", "15m", NOW)), 3)

    def test_malformed_payload_and_wrong_pair_fail(self):
        rows = json.loads(response())["result"]["XXBTZEUR"]
        for raw in (b"not json", b"null", b'{"error":["upstream error"]}',
                    response(rows[::-1]), response([rows[0], rows[0]]),
                    response([[1, "bad"]]), response().replace(b'XXBTZEUR', b'XXBTZUSD'),
                    response().replace(b'"110"', b'"NaN"')):
            with self.subTest(raw=raw), self.assertRaises(MarketDataError):
                self.adapter(raw).fetch_candles("BTC/EUR", "15m", NOW)

    def test_invalid_request_does_not_touch_transport(self):
        transport = Mock()
        adapter = KrakenAdapter(transport, lambda: NOW)
        for symbol, frame, since in (("BTC/USD", "15m", NOW), ("BTC/EUR", "2m", NOW),
                                      ("BTC/EUR", "15m", NOW + timedelta(minutes=1))):
            with self.assertRaises(MarketDataError):
                adapter.fetch_candles(symbol, frame, since)
        transport.assert_not_called()

    def test_private_url_rejected_before_http(self):
        with patch("app.exchange.kraken.build_opener") as opener:
            with self.assertRaises(MarketDataError):
                public_get("https://api.kraken.com/0/private/AddOrder")
            opener.assert_not_called()

    def test_http_failure_has_bounded_retries(self):
        opener = Mock()
        opener.open.side_effect = URLError("offline")
        with patch("app.exchange.kraken.build_opener", return_value=opener), patch("app.exchange.kraken.time.sleep") as sleep:
            with self.assertRaises(MarketDataError):
                public_get(ENDPOINT + "?pair=XBTEUR")
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_nonretryable_error_not_retried(self):
        opener = Mock()
        opener.open.side_effect = HTTPError(ENDPOINT, 403, "denied", {}, None)
        with patch("app.exchange.kraken.build_opener", return_value=opener), patch("app.exchange.kraken.time.sleep") as sleep:
            with self.assertRaises(MarketDataError):
                public_get(ENDPOINT + "?pair=XBTEUR")
        self.assertEqual(opener.open.call_count, 1)
        sleep.assert_not_called()

    def test_response_size_bound(self):
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=Mock(read=Mock(return_value=b"123456")))
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch("app.exchange.kraken.build_opener", return_value=opener), patch("app.exchange.kraken.MAX_RESPONSE_BYTES", 5):
            with self.assertRaises(MarketDataError):
                public_get(ENDPOINT + "?pair=XBTEUR")


class QualityTests(unittest.TestCase):
    def audit(self, candles):
        return audit_candles(candles, "BTC/EUR", "15m", NOW, NOW + timedelta(hours=1),
                             as_of=NOW + timedelta(hours=1))

    def test_complete_precise_data(self):
        report = self.audit(tuple(candle(i) for i in range(4)))
        self.assertTrue(report.ready)
        self.assertEqual(report.expected_rows, 4)

    def test_leading_internal_and_trailing_gaps(self):
        for candles, expected_missing in (((candle(1), candle(2)), 2),
                                         ((candle(0), candle(2), candle(3)), 1), ((), 4)):
            report = self.audit(candles)
            self.assertFalse(report.ready)
            self.assertEqual(report.missing_intervals, expected_missing)
            self.assertEqual(sum(gap["missing_intervals"] for gap in report.gaps), expected_missing)

    def test_duplicates_not_counted_as_coverage(self):
        report = self.audit((candle(0), candle(0), candle(2), candle(3)))
        self.assertEqual(report.missing_intervals, 1)
        self.assertIn("duplicate_timestamp", report.errors)

    def test_off_grid_mixed_and_unfinished_candles(self):
        samples = [(replace(candle(), timestamp=NOW + timedelta(seconds=1)), "off_grid_timestamp"),
                   (replace(candle(), symbol="ETH/EUR"), "mixed_symbol_or_timeframe"),
                   (candle(4), "unfinished_candle")]
        for item, expected in samples:
            with self.subTest(expected=expected):
                report = self.audit((item,))
                self.assertIn(expected, report.errors)
                self.assertFalse(report.ready)

    def test_zero_volume_reported_without_fabrication(self):
        candles = tuple(replace(candle(i), volume=D("0")) for i in range(4))
        report = self.audit(candles)
        self.assertTrue(report.ready)
        self.assertEqual(report.zero_volume_rows, 4)

    def test_gapped_backtest_rejected_before_strategy_or_execution(self):
        strategy, execution = Mock(), Mock()
        with self.assertRaisesRegex(ValueError, "missing=1"):
            Backtester(strategy, execution).run((candle(0), candle(2)))
        strategy.analyze.assert_not_called()
        execution.on_bar.assert_not_called()


class DatasetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.dataset = self.root / "dataset"
        self.candles = tuple(candle(i) for i in range(4))

    def save(self, candles=None):
        return save_dataset(self.dataset, self.candles if candles is None else candles,
                            symbol="BTC/EUR", timeframe="15m", start=NOW, end=NOW + timedelta(hours=1),
                            raw=b"test-source", source={"format": "fixture"},
                            captured_at=NOW + timedelta(hours=1))

    def test_roundtrip_preserves_decimals_and_provenance(self):
        self.save()
        candles, manifest = load_dataset(self.dataset)
        self.assertEqual(candles, self.candles)
        self.assertEqual(manifest["market_type"], "spot")
        self.assertEqual(manifest["source"]["format"], "fixture")
        self.assertEqual(set(manifest["sha256"]), {"source.raw", "candles.csv", "quality.json"})

    def test_file_tampering_rejected(self):
        self.save()
        for name in ("source.raw", "candles.csv", "quality.json"):
            path = self.dataset / name
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "checksum"):
                load_dataset(self.dataset)
            path.write_bytes(original)

    def test_incomplete_source_saved_but_not_usable(self):
        self.assertFalse(self.save((candle(1), candle(2))).ready)
        self.assertTrue((self.dataset / "quality.json").exists())
        with self.assertRaisesRegex(ValueError, "incomplete"):
            load_dataset(self.dataset)

    def test_existing_dataset_not_overwritten(self):
        self.save()
        before = (self.dataset / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.save()
        self.assertEqual((self.dataset / "manifest.json").read_bytes(), before)

    def test_chronological_holdout_split_has_no_overlap(self):
        self.save()
        target = self.root / "split"
        self.assertEqual(split_dataset(self.dataset, target, NOW + timedelta(minutes=30)), (2, 2))
        development = load_candles(target / "development.csv", "BTC/EUR", "15m")
        holdout = load_candles(target / "holdout.csv", "BTC/EUR", "15m")
        self.assertEqual(development + holdout, self.candles)
        self.assertLessEqual(development[-1].closed_at, holdout[0].timestamp)
        for split_at in (NOW, NOW + timedelta(hours=1), NOW + timedelta(minutes=1)):
            with self.assertRaises(ValueError):
                split_dataset(self.dataset, self.root / "invalid", split_at)
        self.assertFalse((self.root / "invalid").exists())

    def test_manifest_cannot_introduce_arbitrary_paths(self):
        self.save()
        path = self.dataset / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["sha256"]["../../another-file"] = "fake"
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            load_dataset(self.dataset)

    def test_malformed_metadata_fails_cleanly(self):
        self.save()
        path = self.dataset / "manifest.json"
        original = path.read_text()
        for key, value in (("symbol", None), ("timeframe", []), ("start", 0), ("end", None)):
            manifest = json.loads(original)
            manifest[key] = value
            path.write_text(json.dumps(manifest))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "metadata"):
                load_dataset(self.dataset)

    def test_archive_csv_and_utc_normalization(self):
        raw = b"1704067200,100,110,90,105,2.12345678,3\n1704068100,100,110,90,105,2.12345678,3\n"
        candles = parse_kraken_csv(raw, "BTC/EUR", "15m", NOW, NOW + timedelta(minutes=30))
        self.assertEqual(candles, self.candles[:2])
        with self.assertRaises(ValueError):
            parse_kraken_csv(raw + raw, "BTC/EUR", "15m", NOW, NOW + timedelta(hours=1))

    def test_csv_header_and_width_validation(self):
        path = self.root / "bad.csv"
        for text in ("timestamp,open,high,low,close,volume,volume\n",
                     "timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,100,110,90,105,2,extra\n"):
            path.write_text(text)
            with self.assertRaises(ValueError):
                load_candles(path, "BTC/EUR", "15m")

    def test_import_cli_reports_gaps_and_preserves_inspection_bundle(self):
        source = self.root / "XBTEUR_15.csv"
        source.write_text("1704067200,100,110,90,105,2,3\n")
        with patch("builtins.print"):
            result = data_main(["import-kraken", "--csv", str(source), "--start", "2024-01-01T00:00:00Z",
                                "--end", "2024-01-01T01:00:00Z", "--output", str(self.dataset)])
        self.assertEqual(result, 2)
        self.assertFalse(json.loads((self.dataset / "manifest.json").read_text())["ready"])

    def test_cli_retention_limit_fails_before_network(self):
        with patch("app.market_data.cli.KrakenAdapter") as adapter, patch("builtins.print"):
            self.assertEqual(data_main(["download", "--bars", "720", "--output", str(self.dataset)]), 1)
        adapter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
