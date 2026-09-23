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
from app.market_data.kraken_perpetual_analytics import (
    KrakenPerpetualAnalyticsAdapter,
    public_get,
)
from app.market_data.kraken_perpetual_monitor import observe, summarize


def payload(kind, stamp, *, more=False):
    timestamp = stamp * 1000 if kind == "funding" else stamp
    if kind == "spreads":
        data = {"bid": {"best_price": ["100"]}, "ask": {"best_price": ["101"]}}
    elif kind == "slippage":
        data = {
            "bid": {f"slippage_{size}": [value] for size, value in
                    zip(("1k", "10k", "100k", "1m"), ("100", "99", "98", None))},
            "ask": {f"slippage_{size}": [value] for size, value in
                    zip(("1k", "10k", "100k", "1m"), ("101", "102", "103", None))},
        }
    else:
        data = {
            "rate": [["0.1", "0.2", "0.0", "0.15"]],
            "relativeRate": [["-0.00001", "0.00003", "-0.00002", "0.00002"]],
        }
    return json.dumps({"result": {"timestamp": [timestamp], "data": data, "more": more},
                       "errors": []}).encode()


class KrakenPerpetualAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 23, 12, 10, 30, tzinfo=timezone.utc)

    def transport(self, url):
        parsed = urlsplit(url)
        kind = parsed.path.rsplit("/", 1)[-1]
        end = int(parse_qs(parsed.query)["to"][0])
        return payload(kind, end - 60)

    def test_combines_timestamp_units_and_derives_adverse_costs(self):
        snapshot = KrakenPerpetualAnalyticsAdapter(self.transport, lambda: self.now).snapshot()
        self.assertEqual(snapshot.event_at, datetime(2026, 9, 23, 12, 9, tzinfo=timezone.utc))
        self.assertEqual((snapshot.bid, snapshot.ask), (Decimal("100"), Decimal("101")))
        self.assertEqual(snapshot.funding_relative_rate, Decimal("0.00002"))
        self.assertEqual(snapshot.slippage_bps["sell_10k"], Decimal("100"))
        self.assertEqual(snapshot.slippage_bps["buy_10k"], Decimal("10000") / Decimal("101"))
        self.assertIsNone(snapshot.slippage_bps["buy_1m"])
        self.assertGreater(snapshot.spread_bps, Decimal("99"))

    def test_rejects_partial_and_inconsistent_payloads(self):
        def partial(url):
            kind = urlsplit(url).path.rsplit("/", 1)[-1]
            end = int(parse_qs(urlsplit(url).query)["to"][0])
            return payload(kind, end - 60, more=kind == "funding")

        with self.assertRaisesRegex(MarketDataError, "funding"):
            KrakenPerpetualAnalyticsAdapter(partial, lambda: self.now).snapshot()

        def favourable(url):
            kind = urlsplit(url).path.rsplit("/", 1)[-1]
            end = int(parse_qs(urlsplit(url).query)["to"][0])
            raw = payload(kind, end - 60)
            if kind == "slippage":
                row = json.loads(raw)
                row["result"]["data"]["ask"]["slippage_10k"] = ["100"]
                return json.dumps(row).encode()
            return raw

        with self.assertRaisesRegex(MarketDataError, "inconsistent"):
            KrakenPerpetualAnalyticsAdapter(favourable, lambda: self.now).snapshot()

    def test_public_transport_rejects_unapproved_url_before_network(self):
        with self.assertRaises(MarketDataError):
            public_get("https://example.com/api/charts/v1/analytics/PF_XBTUSD/spreads?since=1&to=61&interval=60")


class KrakenPerpetualMonitorTests(unittest.TestCase):
    def test_samples_errors_resumes_and_verifies_raw_evidence(self):
        stamp = [datetime(2026, 9, 23, 12, 10, 30, tzinfo=timezone.utc)]
        attempt = [0]
        calls = [0]

        def clock():
            return stamp[0]

        def transport(url):
            calls[0] += 1
            parsed = urlsplit(url)
            kind = parsed.path.rsplit("/", 1)[-1]
            if kind == "spreads":
                attempt[0] += 1
            if attempt[0] == 2 and kind == "slippage":
                raise MarketDataError("fixture outage")
            end = int(parse_qs(parsed.query)["to"][0])
            return payload(kind, end - 60)

        def pause(seconds):
            stamp[0] += timedelta(seconds=seconds)

        deadline = clock() + timedelta(minutes=5)
        adapter = KrakenPerpetualAnalyticsAdapter(transport, clock)
        kwargs = dict(count=3, interval=60, until=deadline, adapter=adapter, clock=clock, pause=pause)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            report = observe(target, **kwargs)
            self.assertEqual((report["attempts"], report["successful"], report["failed"]), (3, 2, 1))
            self.assertEqual(report["estimated_adverse_slippage_bps"]["sell"]["10k"]["median_nearest_rank"], "100.00")
            self.assertTrue(report["raw_integrity_checked"])
            previous_calls = calls[0]
            self.assertEqual(observe(target, **kwargs), report)
            self.assertEqual(calls[0], previous_calls)
            with self.assertRaises(ValueError):
                observe(target, **{**kwargs, "count": 4})
            with closing(sqlite3.connect(target / "observations.sqlite3")) as db:
                db.row_factory = sqlite3.Row
                db.execute("UPDATE attempts SET funding_raw='modified' WHERE ok=1 AND id=(SELECT MIN(id) FROM attempts WHERE ok=1)")
                with self.assertRaises((ValueError, TypeError)):
                    summarize(db, status="test")

    def test_expired_deadline_prevents_network(self):
        now = datetime(2026, 9, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            observe(Path(directory), count=1, interval=60, until=now, clock=lambda: now)
