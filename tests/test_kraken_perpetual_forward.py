import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from app.errors import MarketDataError
from app.market_data.kraken_perpetual_analytics import AnalyticsSnapshot, NOTIONALS
from app.market_data.kraken_perpetual_forward import (
    collect_due,
    load_bundle,
    public_get_price,
)


START = datetime(2026, 9, 24, 8, tzinfo=timezone.utc)
END = START + timedelta(hours=4)
NOW = END + timedelta(minutes=10)


def price_payload(kind):
    volume = "5" if kind == "trade" else "0"
    return json.dumps({"candles": [{
        "time": int(START.timestamp() * 1000), "open": "100", "high": "105",
        "low": "95", "close": "102", "volume": volume,
    }], "more_candles": False}).encode()


def regime_payload(kind):
    if kind == "open-interest":
        data = [["100", "102", "99", "101"]]
    elif kind == "cvd":
        data = {"buy_volume": ["3"], "sell_volume": ["2"], "cvd": ["10"]}
    else:
        data = [{"aggressor-differential": "1", "liquidation-volume": "0",
                 "rolling-volatility": "1.5", "long-short-ratio": "0.6"}[kind]]
    return json.dumps({"result": {"timestamp": [int(START.timestamp())],
                                  "data": data, "more": False}, "errors": []}).encode()


def funding_payload():
    stamps = [int((START + timedelta(hours=index)).timestamp() * 1000) for index in range(4)]
    rates = [["0", "0", "0", "0.00001"] for _ in stamps]
    return json.dumps({"result": {"timestamp": stamps,
                                  "data": {"rate": rates, "relativeRate": rates},
                                  "more": False}, "errors": []}).encode()


class CostAdapter:
    def __init__(self):
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        prices = {}
        for notional in NOTIONALS:
            prices[f"sell_{notional}"] = Decimal("99")
            prices[f"buy_{notional}"] = Decimal("102")
        return AnalyticsSnapshot(
            "PF_XBTUSD", END, NOW, NOW, Decimal("100"), Decimal("101"),
            Decimal("0.00001"), prices,
            {"spreads": b"spread", "slippage": b"slippage", "funding": b"funding"},
            {"spreads": "https://futures.kraken.com/spreads",
             "slippage": "https://futures.kraken.com/slippage",
             "funding": "https://futures.kraken.com/funding"},
        )


class KrakenPerpetualForwardTests(unittest.TestCase):
    def test_collects_one_immutable_bundle_and_resumes_without_network(self):
        calls = {"price": 0, "regime": 0, "funding": 0}
        adapter = CostAdapter()

        def price_transport(url):
            calls["price"] += 1
            return price_payload(urlsplit(url).path.split("/")[4])

        def regime_transport(url):
            calls["regime"] += 1
            return regime_payload(urlsplit(url).path.rsplit("/", 1)[-1])

        def funding_transport(url):
            calls["funding"] += 1
            return funding_payload()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "forward"
            kwargs = dict(price_transport=price_transport, regime_transport=regime_transport,
                          funding_transport=funding_transport, cost_adapter=adapter,
                          clock=lambda: NOW)
            created = collect_due(root, START, **kwargs)
            self.assertEqual(len(created), 1)
            manifest = load_bundle(created[0])
            self.assertEqual(manifest["components"], [
                "trade_mark_prices", "regime", "hourly_funding", "cost_snapshot",
            ])
            self.assertEqual(calls, {"price": 2, "regime": 6, "funding": 1})
            self.assertEqual(adapter.calls, 1)

            self.assertEqual(collect_due(root, START, **kwargs), ())
            self.assertEqual(calls, {"price": 2, "regime": 6, "funding": 1})
            self.assertEqual(adapter.calls, 1)

    def test_corruption_is_rejected(self):
        adapter = CostAdapter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "forward"
            created = collect_due(
                root, START,
                price_transport=lambda url: price_payload(urlsplit(url).path.split("/")[4]),
                regime_transport=lambda url: regime_payload(urlsplit(url).path.rsplit("/", 1)[-1]),
                funding_transport=lambda url: funding_payload(), cost_adapter=adapter,
                clock=lambda: NOW,
            )
            (created[0] / "cost" / "summary.json").write_text("changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_bundle(created[0])

    def test_unapproved_price_url_is_rejected(self):
        with self.assertRaises(MarketDataError):
            public_get_price(
                "https://example.com/api/charts/v1/trade/PF_XBTUSD/4h?from=1&to=14401"
            )


if __name__ == "__main__":
    unittest.main()
