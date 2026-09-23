import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from app.config.settings import Settings
from app.database.repository import Repository
from app.domain import Direction
from app.errors import MarketDataError
from app.exchange.bitvavo import BookSnapshot, Instrument
from app.execution.durable_paper import DurablePaperBroker
from app.execution.quote_paper import QuotePaperRunner
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.models import Signal
from tests.helpers import D, NOW


class EntryFixture(Strategy):
    def analyze(self, candles):
        return Signal('BTC/EUR', candles[-1].closed_at, Direction.LONG, D('1'),
                      ('Quote execution test only',), 'test', '1', stop_price=D('90'), take_profit_price=D('120'))


class QuotePaperTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'paper.db'
        self.repo = Repository(self.path)
        self.addCleanup(self.repo.connection.close)
        self.settings = Settings(timeframe='4h', paper_fee_rate=D('.0025'), paper_slippage_bps=D('0'), min_order_quantity=D('.01'))
        self.session = self.repo.start_session(self.settings.mode, self.settings.initial_capital, self.settings.symbol)
        self.broker = DurablePaperBroker(self.settings, self.repo, self.session)
        self.now = NOW + timedelta(hours=3, minutes=59, seconds=40)
        self.runner = QuotePaperRunner(self.broker, EntryFixture(), clock=lambda: self.now)
        self.old = Candle('BTC/EUR', '4h', NOW - timedelta(hours=4), D('100'), D('102'), D('98'), D('100'), D('1'))
        self.new = replace(self.old, timestamp=NOW)

    def observe(self, *, bid='99', ask='101', size='10', candles=None):
        quote = BookSnapshot(json.dumps(dict(bid=bid,ask=ask,size=size)).encode(), 'public-quote', self.now,
                             self.now, D(bid), D(size), D(ask), D(size))
        market = Instrument(b'{"fixture":true}', 'public-market', self.now, 'trading',
                            self.settings.price_tick, self.settings.quantity_step,
                            self.settings.min_order_quantity, self.settings.min_order_notional, 'A')
        return quote, market, candles if candles is not None else (self.old, self.new)

    def seed(self):
        self.now += timedelta(seconds=1)
        event = self.runner.process(*self.observe(candles=(self.old,)))
        self.assertIn('Warm-up only', event['actions'][0])
        self.assertEqual(self.repo.records('orders', self.session), [])
        self.now = NOW + timedelta(hours=4, seconds=1)

    def test_uses_subsequent_ask_not_historical_open_and_bid_for_exit(self):
        self.seed()
        event = self.runner.process(*self.observe())
        position = self.broker.snapshot().positions[0]
        self.assertEqual(position.entry_price, D('101'))
        self.assertEqual(position.opened_at, self.now)
        self.assertLess(D(event['equity']), D('1000'))
        self.now += timedelta(minutes=1)
        self.runner.process(*self.observe(bid='80', ask='81', candles=()))
        trade = self.broker.trades[0]
        self.assertEqual(trade.exit_price, D('80'))
        self.assertEqual(trade.exit_reason, 'PAPER_OBSERVED_STOP')
        self.assertEqual(self.broker.snapshot().cash, D('1000') + trade.net_pnl)

    def test_duplicate_quote_and_restart_do_not_duplicate_signal_or_position(self):
        self.seed()
        observation = self.observe()
        self.runner.process(*observation)
        counts = {table:len(self.repo.records(table,self.session)) for table in ('orders','signals','equity')}
        self.assertTrue(self.runner.process(*observation)['duplicate'])
        self.broker = DurablePaperBroker.resume(self.settings, self.repo, self.session)
        self.runner = QuotePaperRunner(self.broker, EntryFixture(), clock=lambda:self.now)
        self.assertTrue(self.runner.process(*observation)['duplicate'])
        self.assertEqual(counts,{table:len(self.repo.records(table,self.session)) for table in counts})
        self.now += timedelta(seconds=5)
        self.runner.process(*self.observe())
        self.assertEqual(len(self.repo.records('orders',self.session)),1)
        self.assertEqual(len(self.repo.records('signals',self.session)),1)

    def test_stale_slow_future_and_changed_instrument_rejected_before_mutation(self):
        self.seed()
        quote, market, candles = self.observe()
        cases = [(replace(quote, requested_at=self.now-timedelta(seconds=20),received_at=self.now-timedelta(seconds=20)),market),
                 (replace(quote, requested_at=self.now-timedelta(seconds=6)),market),
                 (replace(quote, received_at=self.now+timedelta(seconds=1)),market),
                 (quote,replace(market,tick_size=D('1')))]
        before=self.repo.records('paper_checkpoints',self.session)
        for bad_quote,bad_market in cases:
            with self.assertRaises(MarketDataError):
                self.runner.process(bad_quote,bad_market,candles)
        self.assertEqual(before,self.repo.records('paper_checkpoints',self.session))

    def test_delayed_signal_and_insufficient_depth_never_backfill_entry(self):
        self.seed()
        self.now += timedelta(minutes=2)
        event=self.runner.process(*self.observe())
        self.assertIn('expired',event['actions'][0])
        self.assertEqual(self.repo.records('orders',self.session),[])
        self.now += timedelta(seconds=5)
        self.runner.process(*self.observe())
        self.assertEqual(len(self.repo.records('signals',self.session)),1)

    def test_insufficient_displayed_ask_size_blocks_entry(self):
        self.seed()
        event=self.runner.process(*self.observe(size='.00001'))
        self.assertIn('Displayed ask size',event['actions'][0])
        self.assertEqual(self.repo.records('orders',self.session),[])

    def test_revised_or_future_history_blocks_new_entries(self):
        self.seed()
        changed=replace(self.old,close=D('101'))
        event=self.runner.process(*self.observe(candles=(changed,self.new)))
        self.assertIn('revised',event['history_error'])
        self.assertEqual(self.repo.records('orders',self.session),[])
        self.now += timedelta(seconds=1)
        future=replace(self.new,timestamp=NOW+timedelta(hours=4))
        event=self.runner.process(*self.observe(candles=(self.old,self.new,future)))
        self.assertIn('not closed',event['history_error'])

    def test_event_write_failure_rolls_back_signal_order_account_and_runner_progress(self):
        self.seed()
        before=self.broker.snapshot()
        with self.repo.transaction():
            self.repo.connection.execute("CREATE TRIGGER fail_event BEFORE INSERT ON paper_events BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.runner.process(*self.observe())
        self.assertEqual(self.broker.snapshot(),before)
        self.assertEqual(self.repo.records('orders',self.session),[])
        self.assertEqual(self.repo.records('signals',self.session),[])
        with self.repo.transaction():
            self.repo.connection.execute('DROP TRIGGER fail_event')
        self.runner.process(*self.observe())
        self.assertEqual(len(self.repo.records('orders',self.session)),1)

    def test_target_does_not_claim_improved_price(self):
        self.seed()
        self.runner.process(*self.observe())
        self.now += timedelta(minutes=1)
        self.runner.process(*self.observe(bid='130',ask='131'))
        self.assertEqual(self.broker.trades[0].exit_price,D('120'))
        self.assertEqual(self.broker.trades[0].exit_reason,'PAPER_OBSERVED_TARGET')

    def test_current_market_minimum_changes_block_entry_without_resetting_session(self):
        self.seed()
        quote, market, candles = self.observe()
        event = self.runner.process(quote, replace(market, minimum_quantity=D('5')), candles)
        self.assertIn('current market minimums', event['actions'][0])
        self.assertEqual(self.repo.records('orders', self.session), [])
