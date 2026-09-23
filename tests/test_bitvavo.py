import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.errors import MarketDataError
from app.exchange.bitvavo import BitvavoAdapter, public_get
from app.market_data.bitvavo import collect, snapshot
from app.market_data.datasets import load_dataset

START = datetime(2023, 1, 1, tzinfo=timezone.utc)
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def row(at):
    return [int(at.timestamp()) * 1000, "100", "110", "90", "105", "2"]


class BitvavoTests(unittest.TestCase):
    def adapter(self, payload):
        return BitvavoAdapter(lambda url: json.dumps(payload).encode(), lambda: NOW)

    def test_closed_half_open_range_and_descending_response(self):
        urls = []
        def transport(url):
            urls.append(url)
            return json.dumps([row(START + timedelta(hours=4)), row(START)]).encode()
        result = BitvavoAdapter(transport, lambda: NOW).download("BTC/EUR", "4h", START, START + timedelta(hours=8))
        self.assertEqual([c.timestamp for c in result.candles], [START, START + timedelta(hours=4)])
        self.assertEqual(parse_qs(urlsplit(urls[0]).query)["end"], [str(int((START + timedelta(hours=8)).timestamp()) * 1000)])

    def test_bad_rows_fail_instead_of_sorting_or_clipping(self):
        valid = row(START)
        malformed = [valid, valid]
        cases = [malformed, [valid, row(START + timedelta(hours=4))],
                 [row(START - timedelta(hours=4))], [row(START + timedelta(hours=8))],
                 [[valid[0] + 1] + valid[1:]], [[valid[0], "NaN"] + valid[2:]],
                 [[valid[0], 100] + valid[2:]], {"error": "bad"}]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(MarketDataError):
                self.adapter(payload).download("BTC/EUR", "4h", START, START + timedelta(hours=8))

    def test_empty_response_keeps_gap(self):
        self.assertEqual(self.adapter([]).download("BTC/EUR", "4h", START, START + timedelta(hours=4)).candles, ())

    def test_boundaries_rejected_before_network(self):
        calls = []
        adapter = BitvavoAdapter(lambda url: calls.append(url), lambda: NOW)
        for symbol, tf, start, end in [
            ("ETH/EUR", "4h", START, START + timedelta(hours=4)),
            ("BTC/EUR", "4h", START, START + timedelta(hours=4 * 1441)),
            ("BTC/EUR", "4h", START + timedelta(seconds=1), START + timedelta(hours=4)),
            ("BTC/EUR", "4h", NOW, NOW + timedelta(hours=4)),
        ]:
            with self.assertRaises(MarketDataError):
                adapter.download(symbol, tf, start, end)
        self.assertEqual(calls, [])

    def test_private_foreign_and_redirect_like_urls_rejected(self):
        for url in ["https://api.bitvavo.com/v2/orders?market=BTC-EUR",
                    "https://api.bitvavo.com.evil.test/v2/markets?market=BTC-EUR",
                    "https://api.bitvavo.com/v2/markets?market=ETH-EUR",
                    "http://api.bitvavo.com/v2/markets?market=BTC-EUR",
                    "https://api.bitvavo.com/v2/markets?market=BTC-EUR&accessWindow=1"]:
            with self.assertRaises(MarketDataError):
                public_get(url)

    def test_instrument_and_book_validation(self):
        market = dict(market="BTC-EUR", base="BTC", quote="EUR", status="trading", quantityDecimals=8,
                      tickSize="1.00", minOrderInBaseAsset="0.00007", minOrderInQuoteAsset="5", feeCategory="A")
        info = self.adapter(market).instrument()
        self.assertEqual(info.tick_size, Decimal("1"))
        self.assertEqual(info.quantity_step, Decimal("0.00000001"))
        quote = dict(market="BTC-EUR", bid="100", ask="101", bidSize="1", askSize="2")
        book = self.adapter(quote).book()
        self.assertEqual(book.received_at, NOW)
        self.assertGreater(book.spread_bps, 0)
        for bad in ({**quote, "ask": "99"}, {**quote, "market": "ETH-EUR"}, {**quote, "bidSize": "0"}):
            with self.assertRaises(MarketDataError):
                self.adapter(bad).book()
        with self.assertRaises(MarketDataError):
            self.adapter({**market, "quantityDecimals": True}).instrument()

    def test_paginated_collection_preserves_boundaries_and_raw_checksums(self):
        calls = []
        def transport(url):
            params = parse_qs(urlsplit(url).query)
            a, b = (int(params[k][0]) // 1000 for k in ("start", "end"))
            calls.append((a, b))
            return json.dumps([row(datetime.fromtimestamp(t, timezone.utc))
                               for t in reversed(range(a, b, 14400))]).encode()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data"
            report = collect(target, "4h", START, START + timedelta(hours=4 * 1441),
                             adapter=BitvavoAdapter(transport, lambda: NOW), pause=lambda _: None)
            self.assertTrue(report.ready)
            candles, manifest = load_dataset(target)
            self.assertEqual(len(candles), 1441)
            self.assertEqual(calls[0][1], calls[1][0])
            self.assertEqual(manifest["source"]["provider"], "Bitvavo")
            self.assertEqual(len(json.loads((target / "source.raw").read_bytes())["pages"]), 2)

    def test_incomplete_dataset_is_saved_but_not_loadable(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data"
            report = collect(target, "4h", START, START + timedelta(hours=8),
                             adapter=self.adapter([row(START)]), pause=lambda _: None)
            self.assertFalse(report.ready)
            with self.assertRaises(ValueError):
                load_dataset(target)
