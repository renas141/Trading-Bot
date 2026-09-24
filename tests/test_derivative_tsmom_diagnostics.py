import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.domain import Direction
from backtesting.derivative_tsmom_diagnostics import summarize


D = Decimal
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def trade(net, direction=Direction.LONG, fees="1", funding="0.5"):
    return SimpleNamespace(
        net_pnl=D(net), fees=D(fees), funding_paid=D(funding),
        position=SimpleNamespace(direction=direction), exit_reason="STOP_LOSS",
        closed_at=NOW,
    )


class TsmomDiagnosticTests(unittest.TestCase):
    def test_summary_uses_net_results_and_costs(self):
        result = summarize([trade("5"), trade("-2", fees="0.2", funding="-0.1")])
        self.assertEqual(result["trades"], 2)
        self.assertEqual(result["wins"], 1)
        self.assertEqual(result["losses"], 1)
        self.assertEqual(result["net_profit"], "3")
        self.assertEqual(result["profit_factor"], "2.5")
        self.assertEqual(result["fees"], "1.2")
        self.assertEqual(result["funding_paid"], "0.4")

    def test_empty_summary_does_not_invent_profit_factor(self):
        result = summarize([])
        self.assertEqual(result["trades"], 0)
        self.assertEqual(result["net_profit"], "0")
        self.assertIsNone(result["profit_factor"])


if __name__ == "__main__":
    unittest.main()
