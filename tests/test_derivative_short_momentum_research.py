import unittest
from decimal import Decimal

from app.derivatives.observed_costs import ObservedCostScenario
from app.derivatives.settings import DerivativeSettings
from backtesting.derivative_short_momentum_research import assess, cost_cases, definition


D = Decimal


def observed():
    return ObservedCostScenario(
        DerivativeSettings(fee_rate=D("0.0005"), spread_bps=D("0.12"), slippage_bps=D("0.74")),
        D("0.000018"), "a" * 64, "fixed fee source",
    )


def runs(net="1", trades=12):
    rows = []
    for year in (2023, 2024, 2025):
        for scenario in ("observed_p95", "double_cost_stress"):
            rows.append({"year": year, "scenario": scenario, "performance": {
                "net_profit": net, "max_drawdown": "0.05", "trades": trades,
                "liquidations": 0, "maximum_leverage_used": 10,
            }})
    return rows


class DerivativeShortMomentumResearchTests(unittest.TestCase):
    def test_definition_fixes_horizon_exit_and_stress(self):
        source = observed()
        protocol = definition(source)
        self.assertEqual(protocol["strategy"]["parameters"]["fast_momentum_bars"], 42)
        self.assertEqual(protocol["strategy"]["parameters"]["slow_momentum_bars"], 168)
        self.assertEqual(protocol["exit"]["maximum_holding_bars"], 42)
        self.assertEqual(cost_cases(source)["double_cost_stress"][0].fee_rate, D("0.0010"))
        self.assertIn("2026", protocol["reserved_holdout"])

    def test_gate_requires_all_years_costs_and_twelve_trades(self):
        self.assertEqual(assess(runs())["selected"], "short_horizon_tsmom")
        failed = runs()
        failed[-1]["performance"]["net_profit"] = "0"
        self.assertIsNone(assess(failed)["selected"])
        self.assertIsNone(assess(runs(trades=11))["selected"])


if __name__ == "__main__":
    unittest.main()
