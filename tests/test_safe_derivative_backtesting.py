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


if __name__ == "__main__":
    unittest.main()
