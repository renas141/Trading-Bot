import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app.errors import MarketDataError
from app.market_data.datasets import save_dataset
from app.market_data.models import Candle
from app.market_data.reconciliation import reconcile
from app.market_data.trade_history import PublicTrade, aggregate_4h, collect, load_evidence, merge_page, parse_page
from tests.helpers import D, NOW


def trade(number, hours, price="100"):
    return [price, "1", int(NOW.timestamp()) + int(hours * 3600), "b", "l", "", number]


def page(rows, cursor):
    return json.dumps({"error": [], "result": {"XXBTZEUR": rows, "last": str(cursor)}}).encode()


def evidence(root, bad_control=False, missing_id=False):
    rows = [trade(1, 1), trade(2, 3, "110"), trade(4 if missing_id else 3, 9, "120"),
            trade(5 if missing_id else 4, 11, "130"), trade(6 if missing_id else 5, 12, "140")]
    replies = iter([page(rows[:2], rows[1][2] * 10**9), page(rows[1:], rows[-1][2] * 10**9)])
    collect(NOW, NOW + timedelta(hours=12), root / "evidence", lambda _: next(replies), lambda _: None)
    candles = (Candle("BTC/EUR", "4h", NOW, D(100), D(110), D(100), D(110), D(2)),
               Candle("BTC/EUR", "4h", NOW + timedelta(hours=8), D(120), D(130), D(120), D(130), D(2)))
    if bad_control:
        candles = (replace(candles[0], volume=D("2.1")), candles[1])
    raw = "\n".join(f"{int(c.timestamp.timestamp())},{c.open},{c.high},{c.low},{c.close},{c.volume},2" for c in candles).encode()
    save_dataset(root / "dataset", candles, symbol="BTC/EUR", timeframe="4h", start=NOW,
                 end=NOW + timedelta(hours=12), raw=raw, captured_at=NOW + timedelta(days=1),
                 source={"format": "official-multipart-ohlcvt-zip-member"})


class TradeHistoryTests(unittest.TestCase):
    def test_pagination_overlap_is_deduplicated_and_end_witness_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence(root)
            rows, manifest = load_evidence(root / "evidence")
            self.assertEqual([r.id for r in rows], [1, 2, 3, 4])
            self.assertEqual(len(manifest["pages"]), 2)
            self.assertEqual(manifest["unique_rows_including_end_witness"], 5)
            raw = root / "evidence/page-0000.json"
            raw.write_bytes(raw.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_evidence(root / "evidence")

    def test_stalled_cursor_and_unfinished_download_never_publish_complete_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence"
            with self.assertRaisesRegex(MarketDataError, "cursor"):
                collect(NOW, NOW + timedelta(hours=12), output, lambda _: page([trade(1, 1)], 1), lambda _: None)
            self.assertFalse((output / "manifest.json").exists())
        with tempfile.TemporaryDirectory() as directory, patch("app.market_data.trade_history.MAX_PAGES", 1):
            output = Path(directory) / "evidence"
            with self.assertRaisesRegex(MarketDataError, "page budget"):
                collect(NOW, NOW + timedelta(hours=12), output,
                        lambda _: page([trade(1, 1)], (int(NOW.timestamp()) + 3600) * 10**9), lambda _: None)
            self.assertFalse((output / "manifest.json").exists())

    def test_wrong_market_and_invalid_trade_values_are_rejected(self):
        valid = json.loads(page([trade(1, 1)], 99))
        valid["result"]["XBTUSD"] = valid["result"].pop("XXBTZEUR")
        with self.assertRaises(MarketDataError):
            parse_page(json.dumps(valid).encode())
        for price in ("NaN", "-1", "Infinity", "0"):
            with self.assertRaises(MarketDataError):
                parse_page(page([trade(1, 1, price)], 99))

    def test_conflicting_duplicates_and_backwards_time_are_rejected(self):
        row = PublicTrade(1, D(100), D(10), D(1), "b", "l", "")
        seen = {1: row}
        with self.assertRaises(MarketDataError):
            merge_page(seen, (replace(row, price=D(11)),), D(0))
        with self.assertRaises(MarketDataError):
            merge_page(seen, (replace(row, id=2, timestamp=D(99)),), D(0))

    def test_empty_intervals_never_create_flat_price_candles(self):
        rows, _ = parse_page(page([trade(1, 1), trade(2, 3, "110")], 99))
        candle = aggregate_4h(rows, NOW, NOW + timedelta(hours=4))[0]
        self.assertEqual((candle.open, candle.close, candle.volume), (D(100), D(110), D(2)))
        with self.assertRaisesRegex(ValueError, "Empty"):
            aggregate_4h(rows, NOW, NOW + timedelta(hours=8))

    def test_empty_gap_requires_both_controls_and_contiguous_ids(self):
        for bad_control, missing_id in ((False, False), (True, False), (False, True)):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                evidence(root, bad_control, missing_id)
                result = reconcile(root / "dataset", root / "evidence", NOW + timedelta(hours=4))
                expected = "unresolved_source_disagreement" if bad_control or missing_id else "empty_in_public_trade_history"
                self.assertEqual(result["classification"], expected)
                self.assertEqual(result["trades_in_gap"], 0)

    def test_modified_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence(root)
            (root / "dataset/source.raw").write_text("changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                reconcile(root / "dataset", root / "evidence", NOW + timedelta(hours=4))
