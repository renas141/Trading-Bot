import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app.database.repository import Repository
from app.market_data.datasets import write_json
from backtesting.net_reward_research import run_case, sha
from backtesting.slow_research import assess, check_holdout_gate, definition, evaluate, freeze, read_protocol, settings_by_cost
from tests.helpers import NOW
from tests.test_strategy import trend_candles


def cases():
    return [{"variant": v, "cost_scenario": cost,
             "performance": {"net_profit": "5", "trades": 20, "max_drawdown": "0.05"}}
            for v in ("original", "net_reward") for cost in settings_by_cost()]


class SlowResearchTests(unittest.TestCase):
    def test_freeze_preserves_sources_and_refuses_modifications(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "experiment"
            protocol = freeze(output)
            self.assertEqual(read_protocol(output / "protocol.json"), protocol)
            with self.assertRaises(FileExistsError):
                freeze(output)
            source = output / "source/backtesting/engine.py"
            source.write_text(source.read_text() + "\n# changed\n")
            with self.assertRaisesRegex(ValueError, "snapshot"):
                read_protocol(output / "protocol.json")

    def test_screen_requires_primary_success_in_every_cost_case(self):
        for field, value in (("net_profit", "0"), ("trades", 19), ("max_drawdown", "0.10")):
            runs = cases()
            runs[-1]["performance"][field] = value
            self.assertFalse(assess(runs)["screen_passed"])
        self.assertTrue(assess(cases())["screen_passed"])
        with self.assertRaises(ValueError):
            assess(cases()[:-1])
        with self.assertRaises(ValueError):
            assess([cases()[0]] * 4)

    def test_gate_recomputes_checks_and_binds_screen_to_protocol_and_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root / "protocol.json"
            protocol.write_text("synthetic protocol")
            output = root / "evaluation"
            output.mkdir()
            manifest = {"sha256": {"candles.csv": "data-hash"}}
            result = {"protocol_sha256": sha(protocol), "input_sha256": "data-hash", "phase": "screen",
                      "screen_passed": True, "segments": [{"name": str(y), "runs": cases()} for y in (2023, 2024)]}

            def publish():
                (output / "results.json").write_text(json.dumps(result))
                (output / "completion.json").write_text(json.dumps({"results_sha256": sha(output / "results.json")}))
            publish()
            check_holdout_gate(protocol, manifest)
            result["segments"][1]["runs"][-1]["performance"]["net_profit"] = "-1"
            publish()
            with self.assertRaisesRegex(ValueError, "reserved"):
                check_holdout_gate(protocol, manifest)
            result["segments"][1]["runs"] = cases()
            publish()
            with self.assertRaises(ValueError):
                check_holdout_gate(protocol, {"sha256": {"candles.csv": "different"}})
            (output / "results.json").write_text(json.dumps(result) + " ")
            with self.assertRaises(ValueError):
                check_holdout_gate(protocol, manifest)

    def test_blocked_holdout_cannot_create_session_or_calculate_benchmark(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze(root / "experiment")
            with patch("backtesting.slow_research.read_input", return_value=((), {"sha256": {"candles.csv": "x"}})), \
                 patch("backtesting.slow_research.run_case") as run, \
                 patch("backtesting.slow_research.benchmarks") as benchmark:
                with self.assertRaises(FileNotFoundError):
                    evaluate(root / "experiment/protocol.json", root / "dataset", "holdout")
                run.assert_not_called()
                benchmark.assert_not_called()
                self.assertFalse((root / "experiment/holdout").exists())

    def test_4h_replay_keeps_closed_candle_timestamps_and_settings(self):
        candles = tuple(replace(c, timeframe="4h", timestamp=NOW + timedelta(hours=4 * i))
                        for i, c in enumerate(trend_candles(60)))
        with tempfile.TemporaryDirectory() as directory, Repository(Path(directory) / "test.db") as repo:
            result = run_case(candles, settings_by_cost()["base"], "net_reward", repo, {"cost_scenario": "base"})
            records = repo.records("signals", result["session_id"])
            self.assertEqual(len(records), 60)
            self.assertEqual(json.loads(records[0]["payload"])["timestamp"], candles[0].closed_at.isoformat())
            self.assertEqual(definition()["settings"]["base"]["timeframe"], "4h")
