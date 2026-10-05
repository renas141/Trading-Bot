import unittest
from decimal import Decimal

from app.domain import Direction
from app.market_data.perpetual_regime_alignment import AlignedRegimeBar
from app.strategies.funding_aware_regime_momentum_v2 import (
    AdaptiveFundingAwareMomentumStrategy,
)
from tests.test_funding_aware_regime_momentum import inputs


D = Decimal


class AdaptiveFundingStrategyTests(unittest.TestCase):
    def test_four_confirmations_produce_full_risk_score_long_and_short(self):
        for short, expected in ((False, Direction.LONG), (True, Direction.SHORT)):
            candles, aligned, funding = inputs(short=short)
            signal = AdaptiveFundingAwareMomentumStrategy(aligned, funding).analyze(candles)
            self.assertEqual(signal.direction, expected)
            self.assertEqual(signal.confidence, D("1"))
            self.assertTrue(any("majority=4/4" in reason for reason in signal.reasons))

    def test_one_noisy_confirmation_failure_trades_at_lower_risk_score(self):
        candles, aligned, funding = inputs(worsening_funding=True)
        signal = AdaptiveFundingAwareMomentumStrategy(aligned, funding).analyze(candles)
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.confidence, D(5) / D(6))
        self.assertTrue(any("FAIL directional current funding" in reason
                            for reason in signal.reasons))

    def test_two_confirmation_failures_hold(self):
        candles, aligned, funding = inputs(worsening_funding=True)
        changed = list(aligned)
        current = changed[-1]
        regime = dict(current.regime)
        regime["open_interest"] = D("500")
        changed[-1] = AlignedRegimeBar(
            current.trade, current.mark, current.regime_timestamp, regime
        )
        signal = AdaptiveFundingAwareMomentumStrategy(changed, funding).analyze(candles)
        self.assertEqual(signal.direction, Direction.HOLD)
        self.assertEqual(signal.confidence, D(4) / D(6))
        self.assertTrue(any("majority=2/4" in reason for reason in signal.reasons))

    def test_future_extension_cannot_change_existing_signal(self):
        candles, aligned, funding = inputs()
        strategy = AdaptiveFundingAwareMomentumStrategy(aligned, funding)
        before = strategy.analyze(candles[:-1])
        after = strategy.analyze(candles[:-1])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
