import unittest
from decimal import Decimal

from app.derivatives.observed_costs import ObservedCostScenario
from app.derivatives.settings import DerivativeSettings
from backtesting.derivative_regime_momentum_research import assess, cost_cases, definition


D = Decimal


def observed():
    return ObservedCostScenario(
        DerivativeSettings(fee_rate=D("0.0005"), spread_bps=D("0.12"),
                           slippage_bps=D("0.74")),
        D("0.000018"), "a" * 64, "fixed fee source",
    )


def runs(net="1", trades=6):
    return [
        {"year": year, "scenario": scenario, "performance": {
            "net_profit": net, "max_drawdown": "0.05", "trades": trades,
            "liquidations": 0, "maximum_leverage_used": 10,
        }}
        for year in (2023, 2024, 2025)
        for scenario in ("observed_p95", "double_cost_stress")
    ]


class DerivativeRegimeMomentumResearchTests(unittest.TestCase):
    def test_definition_fixes_confirmation_timing_and_cost_stress(self):
        source = observed()
        protocol = definition(source)
        parameters = protocol["strategy"]["parameters"]
        self.assertEqual(parameters["fast_momentum_bars"], 42)
        self.assertEqual(parameters["slow_momentum_bars"], 168)
        self.assertEqual(parameters["regime_change_bars"], 42)
        self.assertIn("additional 4h", protocol["timing"]["safety_lag"])
        self.assertEqual(cost_cases(source)["double_cost_stress"][0].fee_rate, D("0.0010"))
        self.assertIn("Eight", protocol["exploration_disclosure"])

    def test_gate_requires_every_year_cost_and_six_trades(self):
        self.assertEqual(assess(runs())["selected"], "regime_confirmed_momentum")
        failed = runs(); failed[-1]["performance"]["net_profit"] = "0"
        self.assertIsNone(assess(failed)["selected"])
        self.assertIsNone(assess(runs(trades=5))["selected"])


if __name__ == "__main__":
    unittest.main()
