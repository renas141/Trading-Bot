import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.errors import MarketDataError
from app.market_data.kraken_perpetual_regime import (
    KrakenPerpetualRegimeAdapter,
    public_get,
)
from app.market_data.kraken_perpetual_regime_monitor import observe, summarize


def payload(kind, stamp, *, more=False):
    if kind == "open-interest":
        data = [["100", "102", "99", "101"]]
    elif kind == "cvd":
        data = {"buy_volume": ["3"], "sell_volume": ["2"], "cvd": ["10"]}
    else:
        values = {
            "aggressor-differential": "1",
            "liquidation-volume": 0,
            "rolling-volatility": 1.5,
            "long-short-ratio": 0.6,
        }
        data = [values[kind]]
    return json.dumps({"result": {"timestamp": [stamp], "data": data, "more": more},
                       "errors": []}).encode()


class KrakenPerpetualRegimeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 24, 6, 10, 30, tzinfo=timezone.utc)

    def transport(self, url):
        parsed = urlsplit(url)
        kind = parsed.path.rsplit("/", 1)[-1]
        end = int(parse_qs(parsed.query)["to"][0])
        return payload(kind, end - 60)

    def test_combines_six_kinds_at_one_timestamp(self):
        snapshot = KrakenPerpetualRegimeAdapter(self.transport, lambda: self.now).snapshot()
        self.assertEqual(snapshot.event_at, datetime(2026, 9, 24, 6, 9, tzinfo=timezone.utc))
        self.assertEqual(snapshot.open_interest, Decimal("101"))
        self.assertEqual(snapshot.aggressor_differential, Decimal("1"))
        self.assertEqual(snapshot.liquidation_volume, Decimal("0"))
        self.assertEqual(snapshot.rolling_volatility, Decimal("1.5"))
        self.assertEqual(snapshot.long_short_ratio, Decimal("0.6"))
        self.assertEqual(snapshot.buy_volume, Decimal("3"))
        self.assertEqual(snapshot.sell_volume, Decimal("2"))
        self.assertEqual(snapshot.cumulative_volume_delta, Decimal("10"))
        self.assertEqual(set(snapshot.raw), {
            "open-interest", "aggressor-differential", "liquidation-volume",
            "rolling-volatility", "long-short-ratio", "cvd",
        })

    def test_rejects_partial_misaligned_and_malformed_series(self):
        def partial(url):
            parsed = urlsplit(url)
            kind = parsed.path.rsplit("/", 1)[-1]
            end = int(parse_qs(parsed.query)["to"][0])
            return payload(kind, end - 60, more=kind == "cvd")

        with self.assertRaisesRegex(MarketDataError, "cvd"):
            KrakenPerpetualRegimeAdapter(partial, lambda: self.now).snapshot()

        def no_common(url):
            parsed = urlsplit(url)
            kind = parsed.path.rsplit("/", 1)[-1]
            end = int(parse_qs(parsed.query)["to"][0])
            return payload(kind, end - (120 if kind == "cvd" else 60))

        with self.assertRaisesRegex(MarketDataError, "no common"):
            KrakenPerpetualRegimeAdapter(no_common, lambda: self.now).snapshot()

        def bad_cvd(url):
            parsed = urlsplit(url)
            kind = parsed.path.rsplit("/", 1)[-1]
            end = int(parse_qs(parsed.query)["to"][0])
            raw = payload(kind, end - 60)
            if kind == "cvd":
                value = json.loads(raw)
                value["result"]["data"]["buy_volume"] = ["-1"]
                return json.dumps(value).encode()
            return raw

        with self.assertRaisesRegex(MarketDataError, "buy volume"):
            KrakenPerpetualRegimeAdapter(bad_cvd, lambda: self.now).snapshot()

    def test_public_transport_rejects_unapproved_url_before_network(self):
        with self.assertRaises(MarketDataError):
            public_get("https://example.com/api/charts/v1/analytics/PF_XBTUSD/cvd?since=1&to=61&interval=60")


class KrakenPerpetualRegimeMonitorTests(unittest.TestCase):
    def test_records_errors_resumes_and_verifies_each_raw_response(self):
        stamp = [datetime(2026, 9, 24, 6, 10, 30, tzinfo=timezone.utc)]
        attempt = [0]
        calls = [0]

        def clock():
            return stamp[0]

        def transport(url):
            calls[0] += 1
            parsed = urlsplit(url)
            kind = parsed.path.rsplit("/", 1)[-1]
            if kind == "open-interest":
                attempt[0] += 1
            if attempt[0] == 2 and kind == "rolling-volatility":
                raise MarketDataError("fixture outage")
            end = int(parse_qs(parsed.query)["to"][0])
            if kind == "cvd":
                stamp[0] += timedelta(seconds=5)
            return payload(kind, end - 60)

        def pause(seconds):
            stamp[0] += timedelta(seconds=seconds)

        adapter = KrakenPerpetualRegimeAdapter(transport, clock)
        kwargs = dict(count=3, interval=60, until=clock() + timedelta(minutes=5),
                      adapter=adapter, clock=clock, pause=pause)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            report = observe(target, **kwargs)
            self.assertEqual((report["attempts"], report["successful"], report["failed"]), (3, 2, 1))
            self.assertEqual(report["metrics"]["open_interest"]["median_nearest_rank"], "101")
            self.assertTrue(report["raw_integrity_checked"])
            previous = calls[0]
            self.assertEqual(observe(target, **kwargs), report)
            self.assertEqual(calls[0], previous)
            with closing(sqlite3.connect(target / "observations.sqlite3")) as db:
                db.row_factory = sqlite3.Row
                db.execute("UPDATE raw_responses SET raw='changed' WHERE rowid=(SELECT MIN(rowid) FROM raw_responses)")
                with self.assertRaises(ValueError):
                    summarize(db, status="test")

    def test_expired_deadline_prevents_network(self):
        now = datetime(2026, 9, 24, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            observe(Path(directory), count=1, interval=60, until=now, clock=lambda: now)


if __name__ == "__main__":
    unittest.main()
