import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.derivatives.observed_costs import load_observed_cost_scenario
from app.market_data.perpetual_cost_calibration import calibrate
from tests.test_perpetual_cost_calibration import completed_summary


D = Decimal


class ObservedCostTests(unittest.TestCase):
    def write_pair(self, root: Path):
        summary = root / "summary.json"
        candidate = root / "candidate.json"
        raw = json.dumps(completed_summary(), sort_keys=True).encode()
        summary.write_bytes(raw)
        candidate.write_text(json.dumps(calibrate(raw), sort_keys=True))
        return candidate, summary

    def test_maps_recomputed_candidate_to_separate_replay_costs(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate, summary = self.write_pair(Path(directory))
            scenario = load_observed_cost_scenario(
                candidate, summary, fee_rate=D("0.0005"), fee_source="Kraken public tier",
            )
            self.assertEqual(scenario.settings.fee_rate, D("0.0005"))
            self.assertEqual(scenario.settings.spread_bps, D("0.5"))
            self.assertEqual(scenario.settings.slippage_bps, D("0.9"))
            self.assertEqual(scenario.settings.adverse_execution_bps, D("1.15"))
            self.assertEqual(scenario.funding_rate_per_4h, D("0.00016"))
            self.assertEqual(scenario.fee_source, "Kraken public tier")

    def test_rejects_tampering_missing_fee_source_and_invalid_fee(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, summary = self.write_pair(root)
            changed = json.loads(candidate.read_text())
            changed["candidate"]["spread_bps_p95"] = "0"
            candidate.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                load_observed_cost_scenario(
                    candidate, summary, fee_rate=D("0.0005"), fee_source="source",
                )
            candidate.write_text(json.dumps(calibrate(summary.read_bytes())))
            with self.assertRaises(ValueError):
                load_observed_cost_scenario(candidate, summary, fee_rate=D("1"), fee_source="source")
            with self.assertRaises(ValueError):
                load_observed_cost_scenario(candidate, summary, fee_rate=D("0.0005"), fee_source=" ")
            summary.write_text(summary.read_text() + " ")
            with self.assertRaises(ValueError):
                load_observed_cost_scenario(
                    candidate, summary, fee_rate=D("0.0005"), fee_source="source",
                )


if __name__ == "__main__":
    unittest.main()
