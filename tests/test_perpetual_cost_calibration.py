import json
import tempfile
import unittest
from pathlib import Path

from app.market_data.perpetual_cost_calibration import calibrate, create


def completed_summary():
    stats = {"minimum": "0.1", "median_nearest_rank": "0.2",
             "p95_nearest_rank": "0.5", "maximum": "0.8"}
    sides = {
        side: {
            size: {**stats, "p95_nearest_rank": value, "available_samples": 475}
            for size, value in (("1k", "0.1"), ("10k", p95), ("100k", "2"), ("1m", "8"))
        }
        for side, p95 in (("buy", "0.7"), ("sell", "0.9"))
    }
    return {
        "configuration": {"market": "PF_XBTUSD", "analytics_interval_seconds": 60},
        "schema_version": 1,
        "provider": "Kraken Futures",
        "market": "PF_XBTUSD",
        "status": "completed",
        "attempts": 480,
        "successful": 475,
        "failed": 5,
        "first_request": "2026-09-23T18:00:00+00:00",
        "last_request": "2026-09-24T02:00:00+00:00",
        "spread_bps": stats,
        "estimated_adverse_slippage_bps": sides,
        "signed_relative_funding_rate": {
            "minimum": "-0.00002", "median_nearest_rank": "0",
            "p95_nearest_rank": "0.00003", "maximum": "0.00004",
            "positive_means_longs_pay": True,
        },
        "max_local_request_seconds": 2.5,
        "max_analytics_bucket_age_seconds": 90,
        "max_gap_between_successful_receipts_seconds": 120,
        "raw_integrity_checked": True,
        "exchange_analytics_timestamp_available": True,
    }


class PerpetualCostCalibrationTests(unittest.TestCase):
    def test_creates_conservative_nonactivating_candidate(self):
        raw = json.dumps(completed_summary(), sort_keys=True).encode()
        result = calibrate(raw)
        self.assertEqual(result["candidate"]["spread_bps_p95"], "0.5")
        self.assertEqual(result["candidate"]["adverse_slippage_bps_p95"], "0.9")
        self.assertEqual(result["candidate"]["adverse_funding_sensitivity_per_4h"], "0.00016")
        self.assertIsNone(result["candidate"]["fee_rate"])
        self.assertEqual(result["activation"], {
            "backtest_changed": False, "paper_enabled": False, "live_enabled": False,
        })
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "summary.json"
            output = Path(directory) / "candidate.json"
            source.write_bytes(raw)
            self.assertEqual(create(source, output), result)
            with self.assertRaises(ValueError):
                create(source, output)

    def test_rejects_short_stale_failed_or_incomplete_evidence(self):
        cases = []
        short = completed_summary()
        short["successful"], short["failed"], short["attempts"] = 359, 0, 359
        cases.append(short)
        stale = completed_summary()
        stale["max_analytics_bucket_age_seconds"] = 181
        cases.append(stale)
        failed = completed_summary()
        failed["successful"], failed["failed"] = 450, 30
        cases.append(failed)
        incomplete = completed_summary()
        incomplete["status"] = "collecting"
        cases.append(incomplete)
        missing_depth = completed_summary()
        missing_depth["estimated_adverse_slippage_bps"]["buy"]["10k"]["available_samples"] = 200
        cases.append(missing_depth)
        for case in cases:
            with self.subTest(case=cases.index(case)), self.assertRaises(ValueError):
                calibrate(json.dumps(case).encode())
