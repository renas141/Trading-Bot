import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.errors import MarketDataError
from app.exchange.bitvavo import BitvavoAdapter
from app.market_data.quote_monitor import observe, summarize


class QuoteMonitorTests(unittest.TestCase):
    def test_samples_errors_and_resume_without_duplicate_attempts(self):
        stamp = [datetime(2026, 9, 23, tzinfo=timezone.utc)]
        clock = lambda: stamp[0]
        calls = [0]
        def transport(url):
            if '/markets?' in url:
                return json.dumps(dict(market='BTC-EUR',base='BTC',quote='EUR',status='trading',quantityDecimals=8,
                                       tickSize='1',minOrderInBaseAsset='0.00007',minOrderInQuoteAsset='5',feeCategory='A')).encode()
            calls[0] += 1
            if calls[0] == 2:
                raise MarketDataError('fixture outage')
            return b'{"market":"BTC-EUR","bid":"100","ask":"101","bidSize":"1","askSize":"2"}'
        def pause(seconds):
            stamp[0] += timedelta(seconds=seconds)
        deadline = clock() + timedelta(minutes=5)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            kwargs = dict(count=3, interval=5, until=deadline, adapter=BitvavoAdapter(transport, clock), clock=clock, pause=pause)
            report = observe(target, **kwargs)
            self.assertEqual((report['attempts'], report['successful'], report['failed']), (3, 2, 1))
            self.assertEqual(report['max_gap_between_successful_receipts_seconds'], 10)
            self.assertFalse(report['exchange_event_timestamp_available'])
            self.assertEqual(observe(target, **kwargs), report)
            self.assertEqual(calls[0], 3)
            with self.assertRaises(ValueError):
                observe(target, **{**kwargs, 'count': 4})
            with closing(sqlite3.connect(target / 'observations.sqlite3')) as db:
                db.row_factory = sqlite3.Row
                db.execute("UPDATE attempts SET raw='modified' WHERE id=1")
                with self.assertRaises((ValueError, TypeError)):
                    summarize(db, status='test')

    def test_expired_deadline_prevents_network(self):
        now = datetime(2026, 9, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            observe(Path(directory), count=1, interval=5, until=now, clock=lambda: now)
