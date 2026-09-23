import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.database.repository import Repository
from app.market_data.datasets import save_dataset
from backtesting.net_reward_research import assess, definition, freeze, read_protocol, read_quarter, run_case, scenarios, validate_dataset
from tests.helpers import D, NOW
from tests.test_strategy import trend_candles


class NetRewardResearchTests(unittest.TestCase):
    def freeze_fixture(self, root):
        spec = definition()
        parent = root / "parent"
        parent.mkdir()
        (parent / "protocol.json").write_text(json.dumps({"protocol_version": "net-reward-comparison-v1",
            "created_at": NOW.isoformat(), "definition": {**spec, "expected_rows": 8640}}))
        start = datetime.fromisoformat(spec["start"])
        candles = tuple(replace(c, timestamp=start + timedelta(minutes=15 * index))
                        for index, c in enumerate(trend_candles(8640)) if index != 3310)
        save_dataset(root / "dataset", candles, symbol="BTC/EUR", timeframe="15m", start=start,
                     end=datetime.fromisoformat(spec["end"]), raw=b"synthetic gapped test fixture",
                     source={"url": spec["source_url"]}, captured_at=datetime.now(timezone.utc))
        return freeze(root / "research", parent / "protocol.json", root / "dataset")

    def test_freeze_roundtrip_rejects_changed_definition_and_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "research"
            frozen = self.freeze_fixture(root)
            self.assertEqual(read_protocol(output / "protocol.json"), frozen)
            with self.assertRaises(FileExistsError):
                freeze(output, root / "parent/protocol.json", root / "dataset")
            changed = dict(frozen)
            changed["definition"] = {**frozen["definition"], "minimum_net_reward_risk": "0.5"}
            (output / "protocol.json").write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                read_protocol(output / "protocol.json")

    def test_code_changes_reject_frozen_experiment(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "research"
            self.freeze_fixture(Path(directory))
            with patch("backtesting.net_reward_research.code_hashes", return_value={}):
                with self.assertRaises(ValueError):
                    read_protocol(output / "protocol.json")

    def test_old_or_wrong_dataset_is_rejected(self):
        spec = definition()
        protocol = {"definition": spec, "amendment": {"original_created_at": NOW.isoformat()}}
        manifest = {key: spec[key] for key in ("symbol", "timeframe", "start", "end")}
        manifest.update(source={"url": spec["source_url"]}, captured_at=(NOW - timedelta(days=1)).isoformat())
        with self.assertRaises(ValueError):
            validate_dataset(trend_candles(80), manifest, protocol)

    def test_declared_gap_is_bound_and_corrupt_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = self.freeze_fixture(root)
            candles, manifest = read_quarter(root / "dataset")
            validate_dataset(candles, manifest, frozen)
            self.assertEqual(len(candles), 8639)
            self.assertEqual(candles[3309].closed_at.isoformat(), frozen["definition"]["segments"][0]["end"])
            self.assertEqual(candles[3310].timestamp.isoformat(), frozen["definition"]["segments"][1]["start"])
            (root / "dataset/source.raw").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                read_quarter(root / "dataset")

    def test_no_amendment_after_parent_evaluation_started(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.freeze_fixture(root)
            (root / "parent/evaluation").mkdir()
            with self.assertRaisesRegex(ValueError, "unevaluated"):
                freeze(root / "other", root / "parent/protocol.json", root / "dataset")

    def test_screen_requires_four_runs_and_does_not_reward_inactivity(self):
        runs = [{"variant": v, "cost_scenario": c, "performance": {"net_profit": "-5" if v == "original" else "0",
                 "trades": 0, "max_drawdown": "0"}} for v in ("original", "net_reward") for c in scenarios()]
        self.assertFalse(assess(runs)["screen_passed"])
        with self.assertRaises(ValueError):
            assess(runs[:3])
        for run in runs:
            if run["variant"] == "net_reward":
                run["performance"].update(net_profit="5", trades=30)
        self.assertTrue(assess(runs)["screen_passed"])
        runs[-1]["performance"]["max_drawdown"] = "0.10"
        self.assertFalse(assess(runs)["screen_passed"])

    def test_actual_runner_records_separate_accounts_and_guard_reasons(self):
        candles = list(trend_candles(60))
        candles[55] = replace(candles[55], open=D("109"), high=D("111"), low=D("108"), close=D("110"), volume=D("12"))
        candles[56] = replace(candles[56], open=D("110"), high=D("111"), low=D("109"), close=D("110"))
        candles[57] = replace(candles[57], open=D("110"), high=D("114"), low=D("109"), close=D("113"))
        settings = replace(scenarios()["base"], paper_fee_rate=D("0"), paper_slippage_bps=D("0"), paper_spread_bps=D("0"))
        with tempfile.TemporaryDirectory() as directory, Repository(Path(directory) / "test.db") as repo:
            runs = [run_case(candles, settings, v, repo, {"cost_scenario": "test"}) for v in ("original", "net_reward")]
            self.assertNotEqual(runs[0]["session_id"], runs[1]["session_id"])
            self.assertEqual(runs[0]["performance"], runs[1]["performance"])
            self.assertEqual(runs[1]["performance"]["trades"], 1)
            entry = json.loads(repo.records("orders", runs[1]["session_id"])[0]["payload"])
            self.assertIn("Net reward/risk filter passed.", entry["reasons"])
