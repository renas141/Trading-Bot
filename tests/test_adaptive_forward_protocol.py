import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backtesting.adaptive_forward_protocol import (
    FORWARD_START,
    VERSION,
    definition,
    freeze,
    read_protocol,
)
from backtesting.adaptive_forward_research import _stage_bounds


class AdaptiveForwardProtocolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.forward = self.root / "forward"
        self.forward.mkdir()
        self.cost = self.root / "cost.json"
        self.summary = self.root / "summary.json"
        self.cost.write_text("{}")
        self.summary.write_text("{}")

    def _bundles(self):
        manifests = {}
        start = FORWARD_START - timedelta(hours=8)
        for index in range(2):
            path = self.forward / f"pf_xbtusd_{index}"
            path.mkdir()
            (path / "bundle.json").write_text(f"bundle-{index}")
            current = start + timedelta(hours=4 * index)
            manifests[path] = {
                "start": current.isoformat(),
                "end": (current + timedelta(hours=4)).isoformat(),
            }
        return manifests

    def test_definition_fixes_tiered_risk_tail_stress_and_no_live_activation(self):
        value = definition()
        self.assertEqual(value["strategy"]["minimum_confirmations"], 3)
        self.assertEqual(value["risk"]["partial_risk_fraction"], "0.005")
        self.assertEqual(value["risk"]["full_risk_fraction"], "0.0125")
        self.assertEqual(value["risk"]["maximum_leverage"], 10)
        self.assertEqual(value["stages"]["screen"]["blocks"], 180)
        self.assertIn("LIVE remains off", value["activation"])
        self.assertEqual(_stage_bounds("screen", 43, 180), (43, 223))
        self.assertEqual(_stage_bounds("holdout", 43, 540), (223, 583))

    def test_freeze_is_hash_bound_and_must_precede_forward_start(self):
        manifests = self._bundles()
        output = self.root / "research" / "protocol.json"
        observed = SimpleNamespace(source_summary_sha256="source")
        with (patch("backtesting.adaptive_forward_protocol.load_bundle",
                    side_effect=lambda path: manifests[path]),
              patch("backtesting.adaptive_forward_protocol.load_observed_cost_scenario",
                    return_value=observed),
              patch("backtesting.adaptive_forward_protocol.code_hashes",
                    return_value={"code": "hash"})):
            protocol = freeze(
                output, self.forward, self.cost, self.summary,
                clock=lambda: FORWARD_START - timedelta(minutes=1),
            )
            self.assertEqual(protocol["protocol_version"], VERSION)
            self.assertFalse(protocol["activation"]["live_enabled"])
            self.assertEqual(read_protocol(output, self.cost, self.summary), protocol)
            changed = json.loads(output.read_text())
            changed["definition"]["risk"]["full_risk_fraction"] = "0.02"
            output.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "integrity"):
                read_protocol(output, self.cost, self.summary)

        late = self.root / "late" / "protocol.json"
        with self.assertRaisesRegex(ValueError, "before"):
            freeze(
                late, self.forward, self.cost, self.summary,
                clock=lambda: FORWARD_START,
            )


if __name__ == "__main__":
    unittest.main()
