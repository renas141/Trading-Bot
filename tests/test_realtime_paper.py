import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from app.derivatives.realtime_paper import (
    CandidateObservation,
    _new_realtime_state,
    _validate_snapshot,
    observe,
    process_snapshot,
    set_halt,
)
from app.derivatives.forward_paper import _restore_broker
from app.derivatives.safety import dynamic_liquidation_price
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction
from app.errors import MarketDataError
from app.market_data.kraken_perpetual_analytics import AnalyticsSnapshot
from app.strategies.models import Signal


D = Decimal
NOW = datetime(2027, 1, 2, 12, 2, tzinfo=timezone.utc)


def snapshot(*, at=NOW, bid="99.99", ask="100.01", mark=None):
    executions = {}
    for size in ("1k", "10k", "100k", "1m"):
        executions[f"sell_{size}"] = D(bid)
        executions[f"buy_{size}"] = D(ask)
    raw = {name: (f'{{"kind":"{name}","at":"{at.isoformat()}"}}').encode()
           for name in ("spreads", "slippage", "funding", "ticker")}
    mark = D(mark) if mark is not None else (D(bid) + D(ask)) / 2
    return AnalyticsSnapshot(
        "PF_XBTUSD", at - timedelta(minutes=1), at - timedelta(seconds=2), at,
        D(bid), D(ask), D("0.00001"), executions, raw,
        {name: f"https://futures.kraken.com/{name}" for name in raw},
        mark, at - timedelta(seconds=1), mark, at - timedelta(seconds=3),
        D("1"), D("1"), at - timedelta(minutes=1),
    )


def long_signal(at=NOW - timedelta(minutes=1)):
    return Signal(
        "BTC/USD", at, Direction.LONG, D("1"), ("Realtime fixture",),
        "test", "1", D("95"), None, D("10"),
    )


class StaticAdapter:
    def __init__(self, value):
        self.value = value

    def snapshot(self):
        return self.value


class RealtimePaperTests(unittest.TestCase):
    def setUp(self):
        self.settings = DerivativeSettings(
            fee_rate=D("0"), spread_bps=D("0"), slippage_bps=D("0")
        )

    def test_stale_quote_is_rejected_before_state_mutation(self):
        stale = snapshot(at=NOW - timedelta(minutes=10))
        with self.assertRaisesRegex(MarketDataError, "stale"):
            _validate_snapshot(stale, NOW, max_quote_age=180, max_request_seconds=30)

    def test_fresh_ticker_cannot_mask_stale_depth_analytics(self):
        value = replace(snapshot(), analytics_event_at=NOW - timedelta(minutes=10))
        with self.assertRaisesRegex(MarketDataError, "stale"):
            _validate_snapshot(value, NOW, max_quote_age=180, max_request_seconds=30)

    def test_observed_quote_entry_uses_safe_leverage_and_protective_exit(self):
        state = _new_realtime_state(self.settings, NOW - timedelta(hours=1))
        state["activated_at"] = (NOW - timedelta(hours=1)).isoformat()
        observation = CandidateObservation(
            long_signal(), NOW - timedelta(minutes=1), D("0"), "bundle", "hash",
            reference_price=D("100"),
        )
        actions = process_snapshot(
            state, self.settings, snapshot(), observation, manual_halt=False,
        )
        self.assertTrue(any(action.startswith("OPEN_LONG_") for action in actions))
        self.assertLessEqual(state["position"]["leverage"], 10)
        stopped = process_snapshot(
            state, self.settings,
            snapshot(at=NOW + timedelta(minutes=1), bid="94", ask="95"),
            None, manual_halt=False,
        )
        self.assertTrue(any("PAPER_REALTIME_STOP" in action for action in stopped))
        self.assertIsNone(state["position"])
        self.assertEqual(len(state["trades"]), 1)

    def test_liquidation_uses_exchange_mark_and_dynamic_margin_threshold(self):
        leveraged = DerivativeSettings(
            fee_rate=D("0"), spread_bps=D("0"), slippage_bps=D("0"),
            max_risk_per_trade=D("0.5"), max_total_risk=D("0.5"),
            max_daily_loss=D("0.5"), max_drawdown=D("0.5"),
            max_margin_fraction=D("0.01"), min_liquidation_buffer=D("0.0001"),
        )
        state = _new_realtime_state(leveraged, NOW - timedelta(hours=1))
        state["activated_at"] = (NOW - timedelta(hours=1)).isoformat()
        process_snapshot(
            state, leveraged, snapshot(),
            CandidateObservation(
                replace(long_signal(), stop_price=D("96")),
                NOW - timedelta(minutes=1), reference_price=D("100")
            ),
            manual_halt=False,
        )
        liquidation = D(str(state["position"]["liquidation_price"]))
        broker = _restore_broker(leveraged, state)
        before_funding = dynamic_liquidation_price(broker._position, broker._funding_paid)
        self.assertGreater(before_funding, liquidation)
        process_snapshot(
            state, leveraged, snapshot(at=NOW + timedelta(minutes=1)),
            CandidateObservation(None, NOW + timedelta(minutes=1), D("0.01")),
            manual_halt=False,
        )
        broker = _restore_broker(leveraged, state)
        after_funding = dynamic_liquidation_price(broker._position, broker._funding_paid)
        self.assertGreater(after_funding, before_funding)
        crossed_mark = (after_funding + before_funding) / 2
        actions = process_snapshot(
            state, leveraged,
            snapshot(at=NOW + timedelta(minutes=2), bid="99.99", ask="100.01",
                     mark=str(crossed_mark)),
            None, manual_halt=False,
        )
        self.assertTrue(any("PAPER_REALTIME_LIQUIDATION" in action for action in actions))
        self.assertIsNone(state["position"])

    def test_manual_halt_blocks_entry_but_keeps_quote_accounting(self):
        state = _new_realtime_state(self.settings, NOW - timedelta(hours=1))
        state["activated_at"] = (NOW - timedelta(hours=1)).isoformat()
        actions = process_snapshot(
            state, self.settings, snapshot(),
            CandidateObservation(long_signal(), NOW - timedelta(minutes=1)),
            manual_halt=True,
        )
        self.assertIn("ENTRY_REJECTED: Manual kill switch is active.", actions)
        self.assertIsNone(state["position"])
        self.assertEqual(state["quote_events"], 1)

    def test_execution_quality_rejects_a_wide_quote(self):
        state = _new_realtime_state(self.settings, NOW - timedelta(hours=1))
        state["activated_at"] = (NOW - timedelta(hours=1)).isoformat()
        actions = process_snapshot(
            state, self.settings, snapshot(bid="99", ask="101"),
            CandidateObservation(
                long_signal(), NOW - timedelta(minutes=1), reference_price=D("100")
            ),
            manual_halt=False,
        )
        self.assertTrue(any("spread" in action.lower() for action in actions))
        self.assertIsNone(state["position"])

    def test_signal_must_match_fresh_candle(self):
        state = _new_realtime_state(self.settings, NOW - timedelta(hours=1))
        state["activated_at"] = (NOW - timedelta(hours=1)).isoformat()
        mismatched = CandidateObservation(
            long_signal(NOW - timedelta(minutes=2)), NOW - timedelta(minutes=1)
        )
        with self.assertRaisesRegex(ValueError, "fresh completed candle"):
            process_snapshot(
                state, self.settings, snapshot(), mismatched, manual_halt=False,
            )

    def test_bounded_observer_persists_and_ignores_duplicate_quote(self):
        proof = {"cost": "fixture"}
        with tempfile.TemporaryDirectory() as directory, patch(
            "app.derivatives.realtime_paper._runtime_settings",
            return_value=(self.settings, proof),
        ):
            output = Path(directory) / "paper"
            result = observe(
                output, Path("candidate"), Path("summary"), count=2, interval=60,
                adapter=StaticAdapter(snapshot()), clock=lambda: NOW,
                pause=lambda _: None,
            )
            self.assertEqual(result["quote_events"], 1)
            self.assertEqual(result["strategy_status"], "no_trade_waiting_for_validation")
            self.assertEqual(len(list((output / "events").glob("*.json"))), 1)
            set_halt(output, True)
            self.assertTrue((output / "HALT.json").is_file())
            set_halt(output, False)
            self.assertFalse((output / "HALT.json").exists())
            resumed = observe(
                output, Path("candidate"), Path("summary"), count=1,
                adapter=StaticAdapter(snapshot()), clock=lambda: NOW,
            )
            self.assertEqual(resumed["quote_events"], 1)


if __name__ == "__main__":
    unittest.main()
