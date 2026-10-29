import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.advance import evaluate_ready_screens
from app.readiness import ReadinessPaths


class AdvanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.paths = ReadinessPaths(
            root / "forward", root / "primary" / "protocol.json",
            root / "cost.json", root / "summary.json", root / "instrument",
            root / "paper", root / "account.json",
            root / "adaptive" / "protocol.json", root / "adaptive" / "amendment.json",
            root / "technical.json", root / "protection" / "protocol.json",
        )

    def _report(self, primary=179, adaptive=179, protection=179):
        return {
            "live_enabled": False,
            "gates": {
                "forward": {"screen": {"collected": primary, "required": 180}},
                "screen": {"status": "not_evaluated"},
                "adaptive_candidate": {
                    "collected": adaptive, "required": 180,
                    "screen": {"status": "not_evaluated"},
                },
                "profit_protection_candidate": {
                    "collected": protection, "required": 180,
                    "screen": {"status": "not_evaluated"},
                },
            },
        }

    def _evaluators(self):
        return {name: Mock() for name in (
            "primary", "adaptive_v2", "profit_protection_v3"
        )}

    def test_incomplete_screens_are_not_evaluated(self):
        evaluators = self._evaluators()
        completed = evaluate_ready_screens(
            self._report(), self.paths, evaluators=evaluators
        )
        self.assertEqual(completed, ())
        self.assertTrue(all(not evaluator.called for evaluator in evaluators.values()))

    def test_each_complete_screen_is_evaluated_once(self):
        evaluators = self._evaluators()
        completed = evaluate_ready_screens(
            self._report(180, 180, 180), self.paths, evaluators=evaluators
        )
        self.assertEqual(completed, (
            "primary", "adaptive_v2", "profit_protection_v3"
        ))
        self.assertTrue(all(evaluator.call_count == 1 for evaluator in evaluators.values()))

        (self.paths.protocol.parent / "screen").mkdir(parents=True)
        (self.paths.adaptive_protocol.parent / "screen").mkdir(parents=True)
        (self.paths.profit_protection_protocol.parent / "screen").mkdir(parents=True)
        completed = evaluate_ready_screens(
            self._report(180, 180, 180), self.paths, evaluators=evaluators
        )
        self.assertEqual(completed, ())
        self.assertTrue(all(evaluator.call_count == 1 for evaluator in evaluators.values()))

    def test_live_or_impossible_progress_is_rejected(self):
        report = self._report(primary=181)
        with self.assertRaisesRegex(ValueError, "progress"):
            evaluate_ready_screens(report, self.paths, evaluators=self._evaluators())
        report["live_enabled"] = True
        with self.assertRaisesRegex(ValueError, "unsafe"):
            evaluate_ready_screens(report, self.paths, evaluators=self._evaluators())


if __name__ == "__main__":
    unittest.main()
