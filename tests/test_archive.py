import io
import re
import unittest
import zipfile
from unittest.mock import patch

from app.errors import MarketDataError
from app.market_data.archive import ARCHIVES, RangeReader, fetch_archive_csv


def zip_bytes(names=("folder/XBTEUR_15.csv",)):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, b"1704067200,100,110,90,105,2,3\n")
    return buffer.getvalue()


def transport_for(raw, bad_etag=False, ignore_range=False):
    def transport(url, method, headers, limit):
        if method == "HEAD":
            return 200, {"content-length": str(len(raw)), "etag": '"stable"'}, b""
        start, end = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", headers["Range"]).groups())
        return (200 if ignore_range else 206), {
            "content-range": f"bytes {start}-{end}/{len(raw)}",
            "etag": '"changed"' if bad_etag else '"stable"'}, raw[start:end + 1]
    return transport


class ArchiveTests(unittest.TestCase):
    def test_fetches_only_selected_csv_and_records_provenance(self):
        raw, metadata, start, end = fetch_archive_csv("2026Q2", "15m", transport_for(zip_bytes()))
        self.assertTrue(raw.startswith(b"1704067200"))
        self.assertEqual(metadata["archive_member"], "folder/XBTEUR_15.csv")
        self.assertEqual(start.isoformat(), "2026-04-01T00:00:00+00:00")
        self.assertEqual(end.isoformat(), "2026-07-01T00:00:00+00:00")

    def test_ambiguous_or_missing_market_rejected(self):
        for names in (("XBTUSD_15.csv",), ("a/XBTEUR_15.csv", "b/XBTEUR_15.csv")):
            with self.assertRaises(MarketDataError):
                fetch_archive_csv("2026Q2", "15m", transport_for(zip_bytes(names)))

    def test_changed_etag_or_ignored_range_rejected(self):
        for flags in ({"bad_etag": True}, {"ignore_range": True}):
            with self.assertRaises(MarketDataError):
                fetch_archive_csv("2026Q2", "15m", transport_for(zip_bytes(), **flags))

    def test_transfer_and_uncompressed_limits(self):
        with patch("app.market_data.archive.MAX_TRANSFER", 1), self.assertRaises(MarketDataError):
            fetch_archive_csv("2026Q2", "15m", transport_for(zip_bytes()))
        with patch("app.market_data.archive.MAX_CSV", 1), self.assertRaises(MarketDataError):
            fetch_archive_csv("2026Q2", "15m", transport_for(zip_bytes()))

    def test_seek_and_empty_read(self):
        reader = RangeReader(ARCHIVES["2026Q2"], transport_for(b"abcdef"))
        with reader:
            self.assertEqual(reader.seek(-2, 2), 4)
            self.assertEqual(reader.read(2), b"ef")
            self.assertEqual(reader.read(2), b"")
            with self.assertRaises(ValueError):
                reader.seek(-1)

    def test_unsupported_archive_is_rejected_without_transport(self):
        with self.assertRaises(ValueError):
            fetch_archive_csv("2025Q1", "15m", lambda *args: self.fail("Network should not run"))
