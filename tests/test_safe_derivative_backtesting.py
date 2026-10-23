import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.derivatives.settings import DerivativeSettings
from app.domain import Direction
from app.market_data.models import Candle
from app.strategies.base import Strategy
from app.strategies.models import Signal
from backtesting.safe_derivatives import SafeDerivativeBacktester
from backtesting.safe_derivatives_v2 import SafeDerivativeBacktester as SafeDerivativeBacktesterV2
from backtesting.safe_derivatives_v3 import ProfitProtectedDerivativeBacktester


D = Decimal
START = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
STEP = timedelta(hours=4)


def candle(index, *, open="100", high="100.5", low="99.5", close="100"):
    return Candle(
        "BTC/USD", "4h", START + STEP * index,
        D(open), D(high), D(low), D(close), D("10"),
    )


class OneLong(Strategy):
    name = "one_long"
    version = "1"

    def analyze(self, history):
        current = history[-1]
        direction = Direction.LONG if len(history) == 1 else Direction.HOLD
        return Signal(
            current.symbol, current.closed_at, direction, D("1"), ("fixture",),
            self.name, self.version, D("99") if direction == Direction.LONG else None,
            None, D("10"),
        )


class AlwaysLong(Strategy):
    name = "always_long"
    version = "1"

    def analyze(self, history):
        current = history[-1]
        return Signal(
            current.symbol, current.closed_at, Direction.LONG, D("1"), ("fixture",),
            self.name, self.version, D("99"), None, D("10"),
        )


class OneShort(Strategy):
    name = "one_short"
    version = "1"

    def analyze(self, history):
        current = history[-1]
        direction = Direction.SHORT if len(history) == 1 else Direction.HOLD
        return Signal(
            current.symbol, current.closed_at, direction, D("1"), ("fixture",),
            self.name, self.version, D("101") if direction == Direction.SHORT else None,
            None, D("10"),
        )


class SafeDerivativeBacktestingTests(unittest.TestCase):
    def setUp(self):
        self.settings = DerivativeSettings(
            fee_rate=D("0"), spread_bps=D("0"), slippage_bps=D("0"),
            max_margin_fraction=D("0.01"),
        )

    def test_safe_ten_x_position_opens_and_closes_without_liquidation(self):
        trade = [candle(0), candle(1), candle(2, close="101", high="101")]
        result = SafeDerivativeBacktester(OneLong(), self.settings).run(
            trade, trade, funding_rates=[D("0"), D("0"), D("0")]
        )
        self.assertEqual(result.entries, 1)
        self.assertEqual(result.trades[0].position.leverage, 10)
        self.assertEqual(result.trades[0].exit_reason, "END_OF_DATA")
        self.assertGreater(result.trades[0].net_pnl, D("0"))
        self.assertEqual(result.performance.liquidations, 0)

    def test_adverse_funding_can_liquidate_a_flat_high_leverage_position(self):
        trade = [candle(0), candle(1), candle(2)]
        result = SafeDerivativeBacktester(OneLong(), self.settings).run(
            trade, trade, funding_rates=[D("0"), D("0.06"), D("0")]
        )
        self.assertEqual(result.entries, 1)
        self.assertEqual(result.funding_liquidations, 1)
        self.assertEqual(result.trades[0].exit_reason, "FUNDING_LIQUIDATION")
        self.assertEqual(result.performance.liquidations, 1)
        self.assertLess(result.trades[0].net_pnl, D("0"))

    def test_unaligned_funding_is_rejected(self):
        trade = [candle(0), candle(1)]
        with self.assertRaisesRegex(ValueError, "funding"):
            SafeDerivativeBacktester(OneLong(), self.settings).run(
                trade, trade, funding_rates=[D("0")]
            )

    def test_v2_ignores_repeated_entry_signals_while_position_is_open(self):
        trade = [candle(index) for index in range(5)]
        result = SafeDerivativeBacktesterV2(AlwaysLong(), self.settings).run(
            trade, trade, funding_rates=[D("0")] * len(trade)
        )
        self.assertEqual(result.entries, 1)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].exit_reason, "END_OF_DATA")

    def test_v3_break_even_stop_uses_close_and_only_applies_to_future_bars(self):
        trade = [
            candle(0),
            candle(1, high="101.5", low="99.5", close="101"),
            candle(2, open="101", high="101", low="99.5", close="100"),
        ]
        result = ProfitProtectedDerivativeBacktester(OneLong(), self.settings).run(
            trade, trade, funding_rates=[D("0")] * len(trade)
        )
        self.assertEqual(result.entries, 1)
        self.assertEqual(result.stop_updates, 1)
        self.assertEqual(result.trades[0].exit_reason, "STOP_LOSS")
        self.assertEqual(result.trades[0].position.stop_price, D("100"))
        self.assertEqual(result.trades[0].net_pnl, D("0"))

    def test_v3_profit_protection_is_symmetric_for_short_positions(self):
        trade = [
            candle(0),
            candle(1, high="100.5", low="98.5", close="99"),
            candle(2, open="99", high="100.5", low="99", close="100"),
        ]
        result = ProfitProtectedDerivativeBacktester(OneShort(), self.settings).run(
            trade, trade, funding_rates=[D("0")] * len(trade)
        )
        self.assertEqual(result.stop_updates, 1)
        self.assertEqual(result.trades[0].position.stop_price, D("100"))
        self.assertEqual(result.trades[0].net_pnl, D("0"))

    def test_v3_gap_through_break_even_uses_the_worse_next_open(self):
        trade = [
            candle(0),
            candle(1, high="101.5", low="99.5", close="101"),
            candle(2, open="99.5", high="100", low="99", close="99.5"),
        ]
        result = ProfitProtectedDerivativeBacktester(OneLong(), self.settings).run(
            trade, trade, funding_rates=[D("0")] * len(trade)
        )
        self.assertEqual(result.stop_updates, 1)
        self.assertEqual(result.trades[0].exit_reason, "STOP_GAP")
        self.assertLess(result.trades[0].exit_price, D("100"))
        self.assertLess(result.trades[0].net_pnl, D("0"))


if __name__ == "__main__":
    unittest.main()
