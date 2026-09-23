import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from app.config.settings import Settings
from app.database.repository import Repository
from app.domain import Direction, TradingMode
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import PaperBroker
from app.market_data.models import Candle
from app.risk.stop_risk import StopRiskManager
from app.strategies.models import Signal
from backtesting.trailing import TrailingExecution
from tests.helpers import D, NOW


class TrailingTests(unittest.TestCase):
    def test_close_based_stop_cannot_hit_earlier_low_and_gap_uses_next_open(self):
        with tempfile.TemporaryDirectory() as directory, Repository(Path(directory)/'test.db') as repo:
            settings=Settings(mode=TradingMode.BACKTEST,timeframe='4h',paper_fee_rate=D('0'),paper_slippage_bps=D('0'))
            session=repo.start_session(settings.mode,settings.initial_capital,settings.symbol)
            broker=PaperBroker(settings,repo,session)
            execution=TrailingExecution(OrderManager(StopRiskManager(settings),broker,repo,session),broker,repo,session)
            for i in range(43):
                execution.on_bar(Candle('BTC/EUR','4h',NOW+timedelta(hours=4*i),D('100'),D('101'),D('99'),D('100'),D('1')),None)
            at=NOW+timedelta(hours=4*43)
            signal=Signal('BTC/EUR',at,Direction.LONG,D('1'),('fixture',),'test','1',stop_price=D('90'))
            execution.on_bar(Candle('BTC/EUR','4h',at,D('100'),D('130'),D('95'),D('130'),D('1')),signal)
            self.assertEqual(len(broker.snapshot().positions),1)
            position=broker.snapshot().positions[0]
            new_stop=execution.active_stop(position)
            self.assertGreater(new_stop,D('95'))
            self.assertEqual(position.stop_price,D('90'))
            self.assertEqual(broker.trades,[]) # New stop cannot retroactively hit this bar's low.
            updates=repo.connection.execute('SELECT * FROM exit_updates').fetchall()
            self.assertEqual(len(updates),1)
            self.assertEqual(updates[0]['effective_from'],(at+timedelta(hours=4)).isoformat())
            execution.on_bar(Candle('BTC/EUR','4h',at+timedelta(hours=4),D('110'),D('115'),D('105'),D('112'),D('1')),None)
            self.assertEqual(broker.trades[0].exit_price,D('110'))
            self.assertEqual(broker.trades[0].exit_reason,'TRAILING_STOP_GAP')

    def test_trailing_rejects_paper_mode(self):
        with tempfile.TemporaryDirectory() as directory, Repository(Path(directory)/'test.db') as repo:
            settings=Settings()
            session=repo.start_session(settings.mode,settings.initial_capital,settings.symbol)
            broker=PaperBroker(settings,repo,session)
            with self.assertRaises(ValueError):
                TrailingExecution(OrderManager(StopRiskManager(settings),broker,repo,session),broker,repo,session)

    def test_gate_requires_each_year_cost_and_does_not_pick_control(self):
        from backtesting.exit_research import assess, variants
        segments=[]
        for year in ('2023','2024'):
            runs=[]
            for name in variants():
                for cost in ('bitvavo_current','bitvavo_stress'):
                    runs.append(dict(variant=name,cost_scenario=cost,performance={
                        'net_profit':'20' if name=='slow_trailing' else '10',
                        'trades':5,'max_drawdown':'.02'}))
            segments.append(dict(name=year,runs=runs))
        self.assertTrue(assess(segments)['screen_passed'])
        segments[1]['runs'][-1]['performance']['net_profit']='-1'
        self.assertFalse(assess(segments)['screen_passed'])
        with self.assertRaises(ValueError):
            assess(segments[:1])
