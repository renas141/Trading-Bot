import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.market_data.kraken_futures import build_dataset, load_futures_dataset, parse_payload


START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2024, 1, 1, 8, tzinfo=timezone.utc)


def payload(kind="trade"):
    volume = "1" if kind == "trade" else "0"
    return json.dumps({"candles": [
        {"time": 1704067200000, "open": "100", "high": "105", "low": "95", "close": "102", "volume": volume},
        {"time": 1704081600000, "open": "102", "high": "106", "low": "100", "close": "104", "volume": volume},
        {"time": 1704096000000, "open": "104", "high": "107", "low": "103", "close": "106", "volume": volume},
    ], "more_candles": False}).encode()


class KrakenFuturesDatasetTests(unittest.TestCase):
    def test_end_boundary_is_excluded(self):
        candles = parse_payload(payload(), "trade", START, END)
        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[-1].closed_at, END)

    def test_build_and_verified_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trade, mark = root / "trade.json", root / "mark.json"
            trade.write_bytes(payload("trade"))
            mark.write_bytes(payload("mark"))
            target = root / "dataset"
            report = build_dataset(target, [trade], [mark], START, END)
            self.assertTrue(report["ready"])
            trade_rows, mark_rows, manifest = load_futures_dataset(target)
            self.assertEqual(len(trade_rows), 2)
            self.assertEqual(len(mark_rows), 2)
            self.assertEqual(manifest["market_id"], "PF_XBTUSD")

    def test_partial_page_is_rejected(self):
        raw = json.dumps({"candles": [], "more_candles": True}).encode()
        with self.assertRaises(ValueError):
            parse_payload(raw, "mark", START, END)


if __name__ == "__main__":
    unittest.main()
