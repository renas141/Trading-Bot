import unittest
from decimal import Decimal

from app.derivatives.observed_costs import ObservedCostScenario
from app.derivatives.settings import DerivativeSettings
from backtesting.perpetual_forward_research import (
    FORWARD_START,
    SCREEN_BLOCKS,
    TOTAL_BLOCKS,
    assess,
    cost_cases,
    definition,
)


D = Decimal


def observed():
    return ObservedCostScenario(
        DerivativeSettings(fee_rate=D("0.0005"), spread_bps=D("0.12"),
                           slippage_bps=D("0.74")),
        D("0.000018"), "a" * 64, "fixed fee source",
    )


def runs(*, net="1", factor="1.3", trades=8, drawdown="0.05"):
    return [
        {"scenario": scenario, "performance": {
            "net_profit": net, "profit_factor": factor, "trades": trades,
            "max_drawdown": drawdown, "liquidations": 0,
            "maximum_leverage_used": 3,
        }}
        for scenario in ("observed_p95_actual_funding",
                         "double_cost_and_funding_stress")
    ]


class PerpetualForwardResearchTests(unittest.TestCase):
    def test_definition_fixes_cutoff_stages_cost_stress_and_no_activation(self):
        source = observed()
        protocol = definition(source)
        self.assertEqual(protocol["forward_start"], FORWARD_START.isoformat())
        self.assertEqual(protocol["stages"]["screen"]["blocks"], SCREEN_BLOCKS)
        self.assertEqual(protocol["stages"]["holdout"]["total_blocks_required"], TOTAL_BLOCKS)
        self.assertIn("cannot activate PAPER", protocol["stages"]["screen"]["purpose"])
        stress = cost_cases(source)["double_cost_and_funding_stress"]
        self.assertEqual(stress.fee_rate, D("0.0010"))
        self.assertIn("numeric funding threshold", protocol["strategy"]["excluded"])

    def test_screen_and_holdout_gates_are_distinct_and_require_both_cost_cases(self):
        self.assertTrue(assess(runs(trades=4, factor="1.10"), "screen")["passed"])
        self.assertFalse(assess(runs(trades=4, factor="1.10"), "holdout")["passed"])
        self.assertTrue(assess(runs(), "holdout")["paper_candidate"])
        failed = runs(); failed[-1]["performance"]["net_profit"] = "0"
        self.assertFalse(assess(failed, "screen")["passed"])
        with self.assertRaises(ValueError):
            assess(runs()[:-1], "screen")


if __name__ == "__main__":
    unittest.main()
