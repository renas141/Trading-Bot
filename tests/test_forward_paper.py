import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.derivatives.forward_paper import (
    PAPER_START,
    _file_sha,
    _load_events,
    _new_state,
    _process_bar,
    _stage_receipt,
    _verify_event_evidence,
    readiness,
)
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction
from app.market_data.models import Candle
from app.strategies.models import Signal


D = Decimal
NOW = datetime(2027, 1, 1, 12, tzinfo=timezone.utc)


def signal(direction=Direction.HOLD, *, timestamp=NOW, stop=None):
    return Signal(
        "BTC/USD", timestamp, direction, D("1"), ("Forward paper fixture",),
        "test", "1", D(stop) if stop else None, None, D("10"),
    )


def candle(start, *, open="100", high="101", low="99.5", close="100"):
    return Candle("BTC/USD", "4h", start, D(open), D(high), D(low), D(close), D("1"))


class ForwardPaperTests(unittest.TestCase):
    def test_paper_start_follows_the_full_frozen_holdout(self):
        self.assertEqual(PAPER_START, datetime(2027, 1, 1, 12, tzinfo=timezone.utc))

    def test_stage_receipt_is_hash_bound_and_requires_paper_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root / "protocol.json"
            protocol.write_text("{}")
            stage = root / "holdout"
            stage.mkdir()
            result = {
                "protocol_sha256": _file_sha(protocol), "stage": "holdout",
                "coverage": {"bundles": 540, "end": PAPER_START.isoformat()},
                "activation": {"paper_enabled": False, "live_enabled": False},
                "assessment": {"passed": True, "paper_candidate": True},
            }
            (stage / "results.json").write_text(json.dumps(result))
            (stage / "completion.json").write_text(json.dumps({
                "results_sha256": _file_sha(stage / "results.json")
            }))
            self.assertEqual(
                _stage_receipt(protocol, "holdout", 540)["coverage"]["bundles"], 540
            )
            result["assessment"]["paper_candidate"] = False
            (stage / "results.json").write_text(json.dumps(result))
            (stage / "completion.json").write_text(json.dumps({
                "results_sha256": _file_sha(stage / "results.json")
            }))
            with self.assertRaisesRegex(ValueError, "activation"):
                _stage_receipt(protocol, "holdout", 540)

    def test_readiness_does_not_open_holdout_before_receipts_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol = Path(directory) / "protocol.json"
            protocol.write_text("{}")
            self.assertEqual(readiness(protocol)["status"], "awaiting_screen")
            (protocol.parent / "screen").mkdir()
            (protocol.parent / "screen" / "completion.json").write_text("{}")
            self.assertEqual(readiness(protocol)["status"], "awaiting_holdout")

    def test_one_bar_engine_opens_with_smallest_leverage_then_stops(self):
        settings = DerivativeSettings(
            fee_rate=D("0"), spread_bps=D("0"), slippage_bps=D("0")
        )
        pending = signal(Direction.LONG, timestamp=NOW, stop="99")
        state = _new_state(settings, pending)
        first = candle(NOW, low="99.5", close="100.5")
        actions = _process_bar(
            state, settings, first, first, D("0.001"),
            signal(timestamp=first.closed_at),
        )
        self.assertIn("OPEN_LONG_4X", actions)
        self.assertIsNotNone(state["position"])
        self.assertEqual(state["position"]["leverage"], 4)
        self.assertIn("FUNDING_", " ".join(actions))

        second = candle(NOW + timedelta(hours=4), open="100", high="100", low="98", close="99")
        actions = _process_bar(
            state, settings, second, second, D("0"),
            signal(timestamp=second.closed_at),
        )
        self.assertIn("STOP_LOSS", actions)
        self.assertIsNone(state["position"])
        self.assertEqual(len(state["trades"]), 1)

    def test_event_log_recovers_state_and_detects_broken_chain(self):
        settings = DerivativeSettings()
        initial = _new_state(settings, signal())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            events = output / "events"
            events.mkdir()
            after = json.loads(json.dumps(initial))
            after["processed_blocks"] = 1
            event = {"sequence": 1, "previous_event_sha256": None, "state_after": after}
            first = events / "00000001.json"
            first.write_text(json.dumps(event))
            recovered = _load_events(output, initial)
            self.assertEqual(recovered["processed_blocks"], 1)
            self.assertEqual(recovered["last_event_sha256"], _file_sha(first))
            second = events / "00000002.json"
            second.write_text(json.dumps({
                "sequence": 2, "previous_event_sha256": _file_sha(first),
                "state_after": {**after, "last_event_sha256": _file_sha(first)},
            }))
            self.assertEqual(_load_events(output, initial)["processed_blocks"], 1)
            third = events / "00000003.json"
            third.write_text(json.dumps({
                "sequence": 3, "previous_event_sha256": "wrong", "state_after": after
            }))
            with self.assertRaisesRegex(ValueError, "chain"):
                _load_events(output, initial)

    def test_event_evidence_count_must_match_state(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "count"):
                _verify_event_evidence(Path(directory), object(), 1)


if __name__ == "__main__":
    unittest.main()
