import unittest

from backtesting.adaptive_forward_protocol_v2 import FORWARD_START, VERSION, definition
from backtesting.adaptive_forward_research_v2 import _stage_bounds


class AdaptiveForwardProtocolV2Tests(unittest.TestCase):
    def test_corrected_protocol_is_future_only_and_binds_v2_replay(self):
        value = definition()
        self.assertEqual(VERSION, "pf-xbtusd-adaptive-funding-forward-v2")
        self.assertEqual(FORWARD_START.isoformat(), "2026-10-05T20:00:00+00:00")
        self.assertIn("second entry", value["supersedes"])
        self.assertEqual(_stage_bounds("screen", 43, 180), (43, 223))
        self.assertEqual(_stage_bounds("holdout", 43, 540), (223, 583))
        self.assertEqual(value["risk"]["maximum_leverage"], 10)
        self.assertIn("LIVE remains off", value["activation"])


if __name__ == "__main__":
    unittest.main()
