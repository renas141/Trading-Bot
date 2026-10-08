import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.derivatives.qualification import build_report, source_hashes, write_report


class DerivativeQualificationTests(unittest.TestCase):
    def test_full_technical_qualification_passes_and_is_paper_only(self):
        report = build_report()
        self.assertTrue(report["passed"])
        self.assertFalse(report["live_enabled"])
        self.assertEqual(
            len(report["checks"]["long_short_leverage_lifecycles"]["completed"]), 20,
        )
        self.assertTrue(report["checks"]["funding_adjusted_liquidation"]["passed"])
        self.assertTrue(report["checks"]["tail_gap_deleveraging"]["passed"])
        self.assertTrue(report["checks"]["unavailable_depth_rejection"]["passed"])
        self.assertTrue(report["checks"]["event_chain_recovery"]["passed"])
        self.assertEqual(report["source_sha256"], source_hashes())

    def test_report_is_written_atomically_and_failure_is_not_certified(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "qualification.json"
            report = build_report()
            write_report(target, report)
            self.assertEqual(json.loads(target.read_text()), report)
        with patch("app.derivatives.qualification._live_lock",
                   return_value={"passed": False}):
            with self.assertRaisesRegex(ValueError, "qualification failed"):
                build_report()


if __name__ == "__main__":
    unittest.main()
