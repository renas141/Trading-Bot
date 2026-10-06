import unittest

from backtesting.market_crash_2022_diagnostic import comparison


def run(strategy, scenario, net, liquidations=0, leverage=3):
    return {
        "strategy": strategy, "scenario": scenario,
        "performance": {
            "net_profit": net, "liquidations": liquidations,
            "maximum_leverage_used": leverage,
        },
    }


class MarketCrash2022DiagnosticTests(unittest.TestCase):
    def test_comparison_keeps_each_fixed_rule_and_cost_case_separate(self):
        runs = [
            run("dual_horizon", "observed_p95", "-1"),
            run("dual_horizon", "double_cost_stress", "-2"),
            run("short_horizon", "observed_p95", "3"),
            run("short_horizon", "double_cost_stress", "1"),
        ]
        value = comparison(runs)
        self.assertFalse(value["dual_horizon"]["observed_p95"]["positive_net"])
        self.assertTrue(value["short_horizon"]["double_cost_stress"]["positive_net"])
        self.assertTrue(value["short_horizon"]["double_cost_stress"]["no_liquidation"])


if __name__ == "__main__":
    unittest.main()
