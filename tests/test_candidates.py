import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from app.domain import Direction
from app.market_data.models import Candle
from app.strategies.trend_pullback import PullbackParameters, TrendPullbackStrategy
from backtesting.candidate_research import CANDIDATES, assess, make_candidate, selected_candidate, settings_by_cost
from backtesting.history import CandleHistory
from backtesting.net_reward_research import sha
from tests.helpers import D, NOW


def segments():
    return [{"name": str(year), "runs": [{"variant": v, "cost_scenario": cost,
             "performance": {"net_profit": "10" if v == "slow_breakout" else "20", "trades": 5, "max_drawdown": "0.05"}}
             for v in CANDIDATES for cost in settings_by_cost()]} for year in (2023, 2024)]


class CandidateTests(unittest.TestCase):
    def test_pullback_requires_cross_trend_reversal_and_volume(self):
        closes = [100] * 271 + [120] * 28 + [110, 125]
        candles = tuple(Candle("BTC/EUR", "4h", NOW + timedelta(hours=4*i), D(c), D(c+1), D(c-1), D(c), D(1))
                        for i, c in enumerate(closes))
        strategy = TrendPullbackStrategy()
        result = strategy.analyze(candles)
        self.assertEqual(result.direction, Direction.LONG)
        self.assertEqual(result.confidence, D(1))
        self.assertEqual(result.take_profit_price - candles[-1].close, 3 * (candles[-1].close - result.stop_price))
        self.assertEqual(strategy.analyze(candles[:-1]).direction, Direction.HOLD)
        self.assertEqual(strategy.analyze(candles[:-1] + (replace(candles[-1], volume=D(0)),)).direction, Direction.HOLD)
        history = CandleHistory(candles + (replace(candles[-1], timestamp=candles[-1].closed_at, close=D(124)),), len(candles))
        self.assertEqual(strategy.analyze(history), result)
        with self.assertRaises(ValueError):
            PullbackParameters(trend_period=True)
        with self.assertRaises(ValueError):
            PullbackParameters(stop_atr_multiple=D("NaN"))

    def test_candidates_are_fixed_and_unknown_names_rejected(self):
        self.assertEqual(make_candidate("slow_breakout").parameters.trend_period, 300)
        self.assertEqual(make_candidate("slow_breakout").parameters.breakout_period, 120)
        self.assertEqual(make_candidate("trend_pullback").parameters.atr_period, 42)
        with self.assertRaises(ValueError):
            make_candidate("optimized")

    def test_selection_uses_worst_stress_year_and_never_cheap_fee_only_success(self):
        data = segments()
        self.assertEqual(assess(data)["selected"], "trend_pullback")
        for run in data[1]["runs"]:
            if run["variant"] == "trend_pullback" and run["cost_scenario"] == "kraken_stress":
                run["performance"]["net_profit"] = "-1"
        self.assertEqual(assess(data)["selected"], "slow_breakout")
        for group in data:
            for run in group["runs"]:
                if run["cost_scenario"] == "kraken_current":
                    run["performance"]["trades"] = 4
        self.assertIsNone(assess(data)["selected"])
        with self.assertRaises(ValueError):
            assess([])

    def test_holdout_cannot_override_the_fixed_development_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "protocol.json"
            path.write_text("protocol fixture")
            folder = root / "evaluation"
            folder.mkdir()
            data = segments()
            result = {"protocol_sha256": sha(path), "input_sha256": "input", "phase": "development",
                      "segments": data, "selection": assess(data)}
            def publish():
                (folder / "results.json").write_text(json.dumps(result))
                (folder / "completion.json").write_text(json.dumps({"results_sha256": sha(folder / "results.json")}))
            publish()
            self.assertEqual(selected_candidate(path, {"sha256": {"candles.csv": "input"}}), "trend_pullback")
            result["selection"]["selected"] = "slow_breakout"
            publish()
            with self.assertRaises(ValueError):
                selected_candidate(path, {"sha256": {"candles.csv": "input"}})
