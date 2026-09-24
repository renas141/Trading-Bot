import unittest
from decimal import Decimal

from app.derivatives.observed_costs import ObservedCostScenario
from app.derivatives.settings import DerivativeSettings
from backtesting.derivative_tsmom_research import assess, cost_cases, definition


D = Decimal


def observed():
    return ObservedCostScenario(
        DerivativeSettings(fee_rate=D("0.0005"), spread_bps=D("0.12"), slippage_bps=D("0.74")),
        D("0.000018"), "a" * 64, "fixed fee source",
    )


def runs(net="1", trades=3):
    rows = []
    for year in (2023, 2024, 2025):
        for scenario in ("observed_p95", "double_cost_stress"):
            rows.append({"year": year, "scenario": scenario, "performance": {
                "net_profit": net, "max_drawdown": "0.05", "trades": trades,
                "liquidations": 0, "maximum_leverage_used": 10,
            }})
    return rows


class DerivativeTsmomResearchTests(unittest.TestCase):
    def test_definition_and_stress_costs_are_fixed(self):
        source = observed()
        cases = cost_cases(source)
        self.assertEqual(cases["double_cost_stress"][0].fee_rate, D("0.0010"))
        self.assertEqual(cases["double_cost_stress"][0].spread_bps, D("0.24"))
        self.assertEqual(cases["double_cost_stress"][0].slippage_bps, D("1.48"))
        self.assertEqual(cases["double_cost_stress"][1], D("0.000036"))
        protocol = definition(source)
        self.assertEqual(protocol["strategy"]["parameters"]["fast_momentum_bars"], 180)
        self.assertEqual(protocol["strategy"]["parameters"]["slow_momentum_bars"], 720)
        self.assertIn("2026", protocol["reserved_holdout"])

    def test_gate_requires_every_year_cost_and_minimum_trades(self):
        self.assertEqual(assess(runs())["selected"], "dual_horizon_tsmom")
        negative = runs(); negative[3]["performance"]["net_profit"] = "-1"
        self.assertIsNone(assess(negative)["selected"])
        self.assertIsNone(assess(runs(trades=2))["selected"])


if __name__ == "__main__":
    unittest.main()
