import unittest
from types import SimpleNamespace
from decimal import Decimal

from app.domain import Direction
from backtesting.regime_2026_diagnostic import summarize_directions


class Regime2026DiagnosticTests(unittest.TestCase):
    def test_direction_summary_keeps_counts_wins_and_decimal_net(self):
        trades = [
            SimpleNamespace(position=SimpleNamespace(direction=Direction.LONG),
                            net_pnl=Decimal("3")),
            SimpleNamespace(position=SimpleNamespace(direction=Direction.LONG),
                            net_pnl=Decimal("-1")),
            SimpleNamespace(position=SimpleNamespace(direction=Direction.SHORT),
                            net_pnl=Decimal("2")),
        ]
        result = summarize_directions(trades)
        self.assertEqual(result["LONG"], {"trades": 2, "wins": 1, "net_profit": "2"})
        self.assertEqual(result["SHORT"], {"trades": 1, "wins": 1, "net_profit": "2"})


if __name__ == "__main__":
    unittest.main()
