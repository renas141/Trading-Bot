import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.errors import MarketDataError
from app.market_data.kraken_futures_trades import collect, parse_page, public_get


def payload(start_sequence, count=3):
    rows = []
    for index in range(count):
        sequence = start_sequence + index
        rows.append({
            "time": f"2026-10-06T13:{sequence // 60:02}:{sequence % 60:02}.000000000Z",
            "trade_id": count - index, "price": 86000 + index, "size": "0.01",
            "side": "buy" if index % 2 else "sell", "type": "fill",
            "uid": f"trade-{sequence}", "sequence_id": str(sequence),
        })
    return json.dumps({"result": "success", "history": rows}).encode()


class KrakenFuturesTradesTests(unittest.TestCase):
    def test_public_transport_rejects_wrong_host_and_symbol(self):
        with self.assertRaises(MarketDataError):
            public_get("https://example.com/derivatives/api/v3/history?symbol=PF_XBTUSD")
        with self.assertRaises(MarketDataError):
            public_get("https://futures.kraken.com/derivatives/api/v3/history?symbol=PF_ETHUSD")

    def test_parse_rejects_nonchronological_page(self):
        value = json.loads(payload(10))
        value["history"].reverse()
        with self.assertRaises(MarketDataError):
            parse_page(json.dumps(value).encode())

    def test_empty_success_page_marks_available_history_end(self):
        self.assertEqual(parse_page(b'{"result":"success","history":[]}'), [])

    def test_partial_liquidation_is_preserved(self):
        value = json.loads(payload(10, 1))
        value["history"][0]["type"] = "partial liquidation"
        self.assertEqual(parse_page(json.dumps(value).encode())[0]["type"], "partial liquidation")

    def test_collect_paginates_deduplicates_and_writes_integrity_manifest(self):
        calls = []

        def transport(url):
            calls.append(url)
            query = parse_qs(urlsplit(url).query)
            return payload(10 if "lastTime" not in query else 7)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trades"
            summary = collect(
                output, pages=2, transport=transport,
                clock=lambda: datetime(2026, 10, 6, 14, tzinfo=timezone.utc),
            )
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(summary["unique_trades"], 6)
            self.assertEqual(summary["pages"], 2)
            self.assertEqual(len(manifest["pages"]), 2)
            self.assertTrue(summary["raw_integrity_checked"])
            self.assertEqual(len(calls), 2)

    def test_collect_can_start_before_an_exact_prior_cursor(self):
        calls = []

        def transport(url):
            calls.append(parse_qs(urlsplit(url).query))
            return payload(7)

        with tempfile.TemporaryDirectory() as directory:
            cursor = "2026-10-06T13:00:10.000000000Z"
            summary = collect(
                Path(directory) / "older", pages=1, before=cursor, transport=transport,
                clock=lambda: datetime(2026, 10, 6, 14, tzinfo=timezone.utc),
            )
            self.assertEqual(calls[0]["lastTime"], [cursor])
            self.assertEqual(summary["requested_before"], cursor)


if __name__ == "__main__":
    unittest.main()
