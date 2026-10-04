import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app.readiness import (
    FORWARD_START,
    ReadinessPaths,
    build_readiness,
    validate_report,
    write_report,
)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.forward = self.root / "forward"
        self.forward.mkdir()
        self.protocol = self.root / "research" / "protocol.json"
        self.protocol.parent.mkdir()
        self.protocol.write_text('{"protocol_version":"test"}')
        self.cost_candidate = self.root / "candidate.json"
        self.cost_summary = self.root / "summary.json"
        self.cost_candidate.write_text("{}")
        self.cost_summary.write_text("{}")
        self.instrument = self.root / "instrument"
        self.instrument.mkdir()
        self.paper = self.root / "paper"
        self.account_summary = self.root / "account-summary.json"
        observer = self.paper / "pf_xbtusd_realtime_observer"
        observer.mkdir(parents=True)
        (observer / "status.json").write_text(json.dumps({
            "mode": "PAPER", "market": "PF_XBTUSD", "live_enabled": False,
            "status": "paused", "quote_events": 1, "closed_trades": 0,
        }))
        self.paths = ReadinessPaths(
            self.forward, self.protocol, self.cost_candidate, self.cost_summary,
            self.instrument, self.paper, self.account_summary,
        )

    def _make_bundles(self, count=58):
        anchor = FORWARD_START - timedelta(hours=4 * 55)
        manifests = {}
        for index in range(count):
            path = self.forward / f"pf_xbtusd_{index:04}"
            path.mkdir()
            start = anchor + timedelta(hours=4 * index)
            manifests[path] = {
                "start": start.isoformat(), "end": (start + timedelta(hours=4)).isoformat()
            }
        return manifests

    def test_report_counts_only_post_cutoff_bundles_and_stays_blocked(self):
        manifests = self._make_bundles()
        instrument = {
            "ready_for_research": True, "live_enabled": False,
            "server_time": "2026-10-04T00:00:00Z",
            "public_contract": {"maximum_leverage_from_first_tier": 10},
        }
        with (patch("app.readiness.read_protocol", return_value=({"protocol_version": "test"}, object())),
              patch("app.readiness.load_bundle", side_effect=lambda path: manifests[path]),
              patch("app.readiness.load_snapshot", return_value=instrument)):
            report = build_readiness(self.paths, {})
        self.assertEqual(report["overall_status"], "collecting_forward_screen")
        self.assertEqual(report["gates"]["forward"]["verified_bundles"], 58)
        self.assertEqual(report["gates"]["forward"]["screen"]["collected"], 3)
        self.assertFalse(report["profitability_proven"])
        self.assertFalse(report["live_enabled"])
        self.assertFalse(report["gates"]["private_account"]["configured"])
        self.assertFalse(report["gates"]["private_account"]["verified"])
        self.assertEqual(report["gates"]["paper_observer"]["observations"], 1)

        output = self.root / "readiness" / "status.json"
        write_report(output, report)
        self.assertEqual(validate_report(json.loads(output.read_text())), report)

    def test_live_or_incomplete_report_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_report({"schema_version": 1, "market": "PF_XBTUSD", "live_enabled": True})

    def test_redacted_account_evidence_confirms_eligibility_without_credentials(self):
        manifests = self._make_bundles()
        self.account_summary.write_text(json.dumps({
            "schema_version": 1, "verified_at": "2026-10-04T12:00:00+00:00",
            "mode": "read_only",
            "permissions": {"general": "READ_ONLY", "transfer": "NO_ACCESS"},
            "pf_xbtusd": {"accessible": True, "eligible": True,
                           "minimum_trade_size": "0.0001"},
            "order_capability": False, "transfer_capability": False,
        }))
        with (patch("app.readiness.read_protocol", return_value=({"protocol_version": "test"}, object())),
              patch("app.readiness.load_bundle", side_effect=lambda path: manifests[path]),
              patch("app.readiness.load_snapshot", return_value={
                  "ready_for_research": True, "live_enabled": False,
                  "server_time": "2026-10-04T00:00:00Z",
                  "public_contract": {"maximum_leverage_from_first_tier": 10},
              })):
            report = build_readiness(self.paths, {})
        account = report["gates"]["private_account"]
        self.assertTrue(account["verified"])
        self.assertEqual(account["minimum_trade_size"], "0.0001")
        self.assertNotIn("API", json.dumps(account))

    def test_gap_in_forward_evidence_is_rejected(self):
        manifests = self._make_bundles(2)
        second = sorted(manifests)[1]
        manifests[second]["start"] = (FORWARD_START + timedelta(hours=8)).isoformat()
        with (patch("app.readiness.read_protocol", return_value=({"protocol_version": "test"}, object())),
              patch("app.readiness.load_bundle", side_effect=lambda path: manifests[path]),
              patch("app.readiness.load_snapshot", return_value={
                  "ready_for_research": True, "live_enabled": False,
              })):
            with self.assertRaisesRegex(ValueError, "gap"):
                build_readiness(self.paths, {})


if __name__ == "__main__":
    unittest.main()
