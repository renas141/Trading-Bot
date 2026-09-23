import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.config.serialization import decode_settings, encode_settings
from app.config.settings import Settings
from app.database.repository import Repository
from app.exchange.bitvavo import BitvavoAdapter
from app.paper_cli import observe
from tests.helpers import NOW


class PaperObserverTests(unittest.TestCase):
    def test_public_settings_round_trip_preserves_every_risk_and_execution_field(self):
        settings = Settings()
        saved = encode_settings(settings)
        self.assertEqual(decode_settings(saved), settings)
        with self.assertRaises(ValueError):
            decode_settings({**saved, 'unknown': 'value'})
        with self.assertRaises(ValueError):
            decode_settings({**saved, 'paper_fee_rate': .01})

    def test_no_trade_observer_persists_and_resumes_same_session(self):
        stamp = [NOW + timedelta(days=100, hours=3, minutes=59, seconds=40)]
        def clock():
            return stamp[0]
        def pause(seconds):
            stamp[0] += timedelta(seconds=seconds)
        def transport(url):
            if '/markets?' in url:
                data=dict(market='BTC-EUR',base='BTC',quote='EUR',status='trading',quantityDecimals=8,
                          tickSize='1',minOrderInBaseAsset='0.00007',minOrderInQuoteAsset='5',feeCategory='A')
            elif '/candles?' in url:
                query=parse_qs(urlsplit(url).query)
                first,last=int(query['start'][0]),int(query['end'][0])
                data=[[t,'100','105','95','100','1'] for t in reversed(range(first,last,14400000))]
            else:
                data=dict(market='BTC-EUR',bid='99',ask='101',bidSize='100',askSize='100')
            return json.dumps(data).encode()
        adapter=BitvavoAdapter(transport,clock)
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'paper'
            result=observe(target,count=2,interval=60,adapter=adapter,clock=clock,pause=pause)
            self.assertEqual(result['status'],'paused')
            self.assertEqual(result['cash'],'1000')
            self.assertEqual(result['trades'],0)
            pause(60)
            resumed=observe(target,resume=True,count=1,interval=60,adapter=adapter,clock=clock,pause=pause)
            self.assertEqual(result['session_id'],resumed['session_id'])
            with Repository(target/'paper.sqlite3') as repo:
                self.assertEqual(repo.records('orders',result['session_id']),[])
                signals=repo.records('signals',result['session_id'])
                self.assertEqual(len(signals),1)
                self.assertEqual(json.loads(signals[0]['payload'])['direction'],'HOLD')
                self.assertEqual(repo.connection.execute('SELECT COUNT(*) FROM paper_events').fetchone()[0],3)
            with self.assertRaises(ValueError):
                observe(target,count=1,adapter=adapter,clock=clock,pause=pause)
