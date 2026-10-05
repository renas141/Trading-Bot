import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.derivatives.execution_quality import ExecutionQualityGate, ExecutionQuote
from app.domain import Direction


D = Decimal
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


class ExecutionQualityTests(unittest.TestCase):
    def test_fresh_low_cost_quote_allows_long_and_short(self):
        quote = ExecutionQuote(D("9999.5"), D("10000.5"), NOW, D("0.5"))
        gate = ExecutionQualityGate()
        long = gate.evaluate(Direction.LONG, D("10000"), D("9700"), quote, D("0.0005"), NOW)
        short = gate.evaluate(Direction.SHORT, D("10000"), D("10300"), quote, D("0.0005"), NOW)
        self.assertTrue(long.allowed)
        self.assertTrue(short.allowed)
        self.assertLess(long.estimated_cost_to_stop_fraction, D("0.25"))
        self.assertGreater(long.estimated_entry_fill, quote.ask)
        self.assertLess(short.estimated_entry_fill, quote.bid)

    def test_stale_quote_is_denied(self):
        quote = ExecutionQuote(D("9999.5"), D("10000.5"), NOW, D("0"))
        decision = ExecutionQualityGate().evaluate(
            Direction.LONG, D("10000"), D("9700"), quote, D("0.0005"),
            NOW + timedelta(seconds=21),
        )
        self.assertFalse(decision.allowed)
        self.assertIn("stale", decision.reasons[0])

    def test_wide_or_costly_quote_is_denied(self):
        quote = ExecutionQuote(D("9950"), D("10050"), NOW, D("20"))
        decision = ExecutionQualityGate().evaluate(
            Direction.LONG, D("10000"), D("9900"), quote, D("0.0005"), NOW,
        )
        self.assertFalse(decision.allowed)
        self.assertGreater(decision.spread_bps, D("5"))
        self.assertGreater(decision.estimated_cost_to_stop_fraction, D("0.25"))


if __name__ == "__main__":
    unittest.main()
