import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.errors import MarketDataError
from app.market_data.kraken_futures_ticker import (
    TICKERS_URL,
    FuturesTickerSnapshot,
    KrakenFuturesTickerAdapter,
    KrakenRealtimeMarketAdapter,
    public_get,
)
from app.market_data.kraken_perpetual_analytics import AnalyticsSnapshot


NOW = datetime(2027, 1, 2, 12, 0, 2, tzinfo=timezone.utc)


def payload(**changes) -> bytes:
    ticker = {
        "symbol": "PF_XBTUSD",
        "last": 100,
        "lastTime": "2027-01-02T12:00:00.500Z",
        "tag": "perpetual",
        "pair": "XBT:USD",
        "markPrice": 100.05,
        "bid": 100,
        "bidSize": 2.5,
        "ask": 100.1,
        "askSize": 3.5,
        "relativeFundingRate": 0.00001,
        "suspended": False,
        "indexPrice": 100.04,
        "postOnly": False,
    }
    ticker.update(changes)
    return json.dumps({
        "result": "success",
        "serverTime": "2027-01-02T12:00:01.000Z",
        "tickers": [ticker],
    }).encode()


class KrakenFuturesTickerTests(unittest.TestCase):
    def test_parses_current_pf_xbtusd_mark_and_book(self):
        calls = []
        clock_values = iter((NOW - timedelta(seconds=1), NOW))
        adapter = KrakenFuturesTickerAdapter(
            lambda url: calls.append(url) or payload(), lambda: next(clock_values),
        )
        result = adapter.snapshot()
        self.assertEqual(calls, [TICKERS_URL])
        self.assertEqual(result.mark_price, Decimal("100.05"))
        self.assertEqual(result.bid, Decimal("100"))
        self.assertEqual(result.ask_size, Decimal("3.5"))
        self.assertEqual(result.server_time, datetime(2027, 1, 2, 12, 0, 1,
                                                      tzinfo=timezone.utc))

    def test_rejects_suspended_or_crossed_market(self):
        for raw in (payload(suspended=True), payload(bid=101)):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(MarketDataError, "Malformed"):
                    KrakenFuturesTickerAdapter(lambda _: raw, lambda: NOW).snapshot()

    def test_rejects_missing_or_duplicate_instrument(self):
        duplicate = json.loads(payload())
        duplicate["tickers"].append(dict(duplicate["tickers"][0]))
        for raw in (json.dumps({"result": "success", "serverTime": NOW.isoformat(),
                               "tickers": []}).encode(),
                    json.dumps(duplicate).encode()):
            with self.subTest(raw=raw):
                with self.assertRaises(MarketDataError):
                    KrakenFuturesTickerAdapter(lambda _: raw, lambda: NOW).snapshot()

    def test_transport_rejects_any_nonfixed_url_before_network(self):
        for url in (TICKERS_URL + "?symbol=PF_XBTUSD",
                    "https://example.com/derivatives/api/v3/tickers",
                    "http://futures.kraken.com/derivatives/api/v3/tickers"):
            with self.subTest(url=url):
                with self.assertRaisesRegex(MarketDataError, "fixed public"):
                    public_get(url)

    def test_combined_snapshot_anchors_depth_ratios_to_current_book(self):
        executions = {}
        for size in ("1k", "10k", "100k", "1m"):
            executions[f"sell_{size}"] = Decimal("99")
            executions[f"buy_{size}"] = Decimal("102")
        analytics = AnalyticsSnapshot(
            "PF_XBTUSD", NOW - timedelta(minutes=1), NOW - timedelta(seconds=3),
            NOW - timedelta(seconds=2), Decimal("100"), Decimal("101"),
            Decimal("0.00002"), executions,
            {name: name.encode() for name in ("spreads", "slippage", "funding")},
            {name: f"https://futures.kraken.com/{name}"
             for name in ("spreads", "slippage", "funding")},
        )
        ticker = FuturesTickerSnapshot(
            "PF_XBTUSD", NOW - timedelta(seconds=1), NOW - timedelta(seconds=2),
            NOW - timedelta(seconds=2), NOW, Decimal("200"), Decimal("202"),
            Decimal("1"), Decimal("2"), Decimal("201"), Decimal("200.5"),
            Decimal("200.1"), Decimal("0.00003"), payload(),
        )

        class Static:
            def __init__(self, value):
                self.value = value

            def snapshot(self):
                return self.value

        result = KrakenRealtimeMarketAdapter(Static(analytics), Static(ticker)).snapshot()
        self.assertEqual(result.bid, Decimal("200"))
        self.assertEqual(result.mark_price, Decimal("201"))
        self.assertEqual(result.funding_relative_rate, Decimal("0.00003"))
        self.assertEqual(result.slippage_bps, analytics.slippage_bps)
        self.assertEqual(set(result.raw), {"spreads", "slippage", "funding", "ticker"})


if __name__ == "__main__":
    unittest.main()
