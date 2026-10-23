import unittest

from backtesting.profit_protection_forward_protocol_v3 import (
    FORWARD_START,
    VERSION,
    definition,
)
from backtesting.profit_protection_forward_research_v3 import _stage_bounds


class ProfitProtectionForwardV3Tests(unittest.TestCase):
    def test_protocol_is_future_only_and_binds_causal_break_even_replay(self):
        value = definition()
        self.assertEqual(VERSION, "pf-xbtusd-profit-protection-forward-v3")
        self.assertEqual(FORWARD_START.isoformat(), "2026-10-10T16:00:00+00:00")
        self.assertEqual(value["profit_protection"]["new_stop"],
                         "entry price (0R), active from the following candle only")
        self.assertIn("cannot replace", value["multiple_hypothesis_rule"])
        self.assertEqual(_stage_bounds("screen", 43, 180), (43, 223))
        self.assertEqual(_stage_bounds("holdout", 43, 540), (223, 583))
        self.assertEqual(value["risk"]["maximum_leverage"], 10)
        self.assertIn("LIVE remains off", value["activation"])


if __name__ == "__main__":
    unittest.main()
