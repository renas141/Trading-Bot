import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app.market_data.reconciliation import reconcile
from backtesting.gap_research import assess, check_gate, read_input, settings_by_cost
from backtesting.net_reward_research import json_value, sha
from tests.helpers import NOW
from tests.test_trade_history import evidence


def cases():
    return [{"variant": v, "cost_scenario": c, "performance": {"net_profit": "10", "trades": 20, "max_drawdown": "0.09"}}
            for v in ("original", "net_reward") for c in settings_by_cost()]


class GapResearchTests(unittest.TestCase):
    def test_all_costs_must_pass_and_control_cannot_replace_failed_primary(self):
        self.assertTrue(assess(cases())["screen_passed"])
        runs = cases()
        runs[-1]["performance"]["net_profit"] = "-1"
        self.assertFalse(assess(runs)["screen_passed"])
        with self.assertRaises(ValueError):
            assess(cases()[:-1])
        runs = cases()
        runs[-1]["performance"]["trades"] = 19
        self.assertFalse(assess(runs)["screen_passed"])

    def test_raw_evidence_is_rechecked_and_open_time_never_precedes_trade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence(root)
            audit = json_value(reconcile(root / "dataset", root / "evidence", NOW + timedelta(hours=4)))
            protocol = {"input_manifest_sha256": sha(root / "dataset/manifest.json"),
                        "definition": {"symbol": "BTC/EUR", "timeframe": "4h", "start": NOW.isoformat(), "end": (NOW + timedelta(hours=12)).isoformat()},
                        "gap_evidence": [{"directory": str(root / "evidence"), "audit": audit}]}
            candles, _, gaps = read_input(root / "dataset", protocol)
            self.assertEqual(len(candles), 2)
            self.assertEqual(gaps[0].first_observation_at, NOW + timedelta(hours=9))
            (root / "evidence/page-0000.json").write_text("changed")
            with self.assertRaises(ValueError):
                read_input(root / "dataset", protocol)

    def test_holdout_requires_both_years_and_current_fee_stress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root / "protocol.json"
            protocol.write_text("test protocol")
            output = root / "evaluation"
            output.mkdir()
            manifest = {"sha256": {"candles.csv": "data"}}
            result = {"protocol_sha256": sha(protocol), "input_sha256": "data", "phase": "screen",
                      "segments": [{"name": str(y), "runs": cases()} for y in (2023, 2024)]}
            def publish():
                (output / "results.json").write_text(json.dumps(result))
                (output / "completion.json").write_text(json.dumps({"results_sha256": sha(output / "results.json")}))
            publish()
            check_gate(protocol, manifest)
            result["segments"][-1]["runs"][-1]["performance"]["net_profit"] = "0"
            publish()
            with self.assertRaisesRegex(ValueError, "Holdout"):
                check_gate(protocol, manifest)
