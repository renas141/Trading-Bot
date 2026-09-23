import io
import re
import unittest
import zipfile
from unittest.mock import patch

from app.errors import MarketDataError
from app.market_data.full_archive import PARTS, MultipartReader, fetch_full_csv, request_part


def transport_for_parts(raw, changed=False):
    boundaries = [len(raw) * i // 5 for i in range(6)]
    pieces = {url: raw[boundaries[i]:boundaries[i + 1]] for i, url in enumerate(PARTS)}

    def transport(url, method, headers, limit):
        piece = pieces[url]
        if method == "HEAD":
            return 200, {"content-length": str(len(piece)), "etag": '"stable"'}, b""
        start, end = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", headers["Range"]).groups())
        return 206, {"content-range": f"bytes {start}-{end}/{len(piece)}",
                     "etag": '"changed"' if changed else '"stable"'}, piece[start:end + 1]
    return transport


class FullArchiveTests(unittest.TestCase):
    def test_failed_initialization_can_close_partial_readers(self):
        reader = MultipartReader.__new__(MultipartReader)
        with patch("app.market_data.full_archive.RangeReader", side_effect=MarketDataError("offline")):
            with self.assertRaises(MarketDataError):
                reader.__init__()
        reader.close()
        self.assertTrue(reader.closed)

    def test_cross_part_reads_seeks_eof_and_combined_budget(self):
        raw = b"abcdefghijklmnopqrstuvwxyz"
        with MultipartReader(transport_for_parts(raw)) as reader:
            reader.seek(3)
            self.assertEqual(reader.read(16), raw[3:19])
            reader.seek(-6, 2)
            self.assertEqual(reader.read(), raw[-6:])
            self.assertEqual(reader.read(20), b"")
            reader.seek(0)
            with patch("app.market_data.full_archive.MAX_TRANSFER", 25), self.assertRaises(MarketDataError):
                reader.read(4)
            with self.assertRaises(ValueError):
                reader.seek(-1)

    def test_zip_member_can_span_multiple_parts(self):
        buffer = io.BytesIO()
        expected = b"1704067200,100,110,90,105,2,3\n" * 100
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("folder/XBTEUR_240.csv", expected)
            archive.writestr("folder/XBTUSD_240.csv", b"unrelated")
        raw, metadata = fetch_full_csv("4h", transport_for_parts(buffer.getvalue()))
        self.assertEqual(raw, expected)
        self.assertEqual(len(metadata["parts"]), 5)
        self.assertIn("not verified", metadata["verification"])
        with self.assertRaises(MarketDataError):
            fetch_full_csv("4h", transport_for_parts(buffer.getvalue(), changed=True))

    def test_crc_corruption_and_ambiguous_members_are_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("XBTEUR_240.csv", b"known payload")
        corrupted = buffer.getvalue().replace(b"known payload", b"wrong payload")
        with self.assertRaises(MarketDataError):
            fetch_full_csv("4h", transport_for_parts(corrupted))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("a/XBTEUR_240.csv", b"a")
            archive.writestr("b/XBTEUR_240.csv", b"b")
        with self.assertRaises(MarketDataError):
            fetch_full_csv("4h", transport_for_parts(buffer.getvalue()))

    def test_unapproved_url_and_interval_are_rejected_before_network(self):
        with self.assertRaises(MarketDataError):
            request_part("https://example.com/archive", "HEAD", {}, 0)
        with self.assertRaises(ValueError):
            fetch_full_csv("1m", lambda *args: self.fail("Must not fetch"))
