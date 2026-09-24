import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.market_data.datasets import save_dataset
from backtesting.research import research
from dashboard.data import ResearchStore, compress_equity
from dashboard.server import handler_for
from tests.helpers import D, NOW
from tests.test_strategy import trend_candles


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


def request(store, target="/api/catalog", *, method="GET", host="127.0.0.1:8765", headers=""):
    """Exercise the actual HTTP handler without binding sockets in unit tests."""
    handler_type = handler_for(store)
    handler = object.__new__(handler_type)
    handler.server = SimpleNamespace(server_address=("127.0.0.1", 8765))
    handler.client_address = ("127.0.0.1", 12345)
    handler.rfile = io.BytesIO(f"{method} {target} HTTP/1.1\r\nHost: {host}\r\n{headers}\r\n".encode())
    handler.wfile = io.BytesIO()
    with patch.object(handler_type, "log_message"):
        handler.handle_one_request()
    head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    return int(head.split()[1]), head, body


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.research = self.root / "research"
        candles = list(trend_candles(80))
        candles[55] = replace(candles[55], open=D("109"), high=D("111"), low=D("108"), close=D("110"), volume=D("12"))
        candles[56] = replace(candles[56], open=D("110"), high=D("111"), low=D("109"), close=D("110"))
        candles[57] = replace(candles[57], open=D("110"), high=D("114"), low=D("109"), close=D("113"))
        save_dataset(self.root / "dataset", candles, symbol="BTC/EUR", timeframe="15m", start=NOW,
                     end=candles[-1].closed_at, raw=b"dashboard fixture", source={"format": "fixture"}, captured_at=NOW + timedelta(days=2))
        with patch("builtins.print"):
            research(self.root / "dataset", candles[60].timestamp, self.research / "experiment")
        self.store = ResearchStore(self.research)
        self.study = self.store.catalog()[0][0]
        self.run_id = self.study["groups"][0]["runs"][0]["id"]

    def test_read_only_connection_and_all_reads_leave_sources_unchanged(self):
        before = snapshot(self.research)
        with self.store.connection(self.run_id) as (db, source, session):
            self.assertEqual(session["mode"], "BACKTEST")
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM sessions")
        self.store.run(self.run_id)
        self.store.trades(self.run_id, 0, "all")
        self.store.signals(self.run_id, 0, "all", "ALL")
        self.store.report(self.study["id"])
        self.assertEqual(snapshot(self.research), before)

    def test_trade_has_actual_entry_reasons_and_net_values(self):
        detail = self.store.run(self.run_id)
        result = self.store.trades(self.run_id, 0, "all")
        self.assertEqual(result["total"], 1)
        trade = result["items"][0]
        self.assertTrue(any("PASS Breakout" in r for r in trade["entry_reasons"]))
        self.assertEqual(D(trade["net_pnl"]), D(detail["performance"]["net_profit"]))
        self.assertEqual(D(detail["initial_capital"]) + D(trade["net_pnl"]), D(detail["final_equity"]))
        outcome = "win" if D(trade["net_pnl"]) > 0 else "loss"
        self.assertEqual(self.store.trades(self.run_id, 0, outcome)["total"], 1)
        self.assertEqual(self.store.trades(self.run_id, 0, "loss" if outcome == "win" else "win")["total"], 0)

    def test_signal_filters_and_pagination_are_disjoint(self):
        first = self.store.signals(self.run_id, 0, "all", "ALL")
        second = self.store.signals(self.run_id, 1, "all", "ALL")
        self.assertEqual(first["total"], 60)
        self.assertEqual(len(first["items"]), 12)
        self.assertFalse({r["signal"]["timestamp"] for r in first["items"]} & {r["signal"]["timestamp"] for r in second["items"]})
        approved = self.store.signals(self.run_id, 0, "allowed", "LONG")
        self.assertEqual(approved["total"], 1)
        self.assertTrue(approved["items"][0]["decision"]["allowed"])
        self.assertEqual(self.store.signals(self.run_id, 0, "allowed", "HOLD")["total"], 0)

    def test_zero_trade_run_remains_valid(self):
        empty_id = self.study["groups"][1]["runs"][0]["id"]
        detail = self.store.run(empty_id)
        self.assertEqual(detail["performance"]["trades"], 0)
        self.assertEqual(D(detail["final_equity"]), D("1000"))
        self.assertEqual(self.store.trades(empty_id, 0, "all")["items"], [])

    def test_segmented_study_keeps_accounts_and_benchmarks_separate(self):
        original = self.research / "experiment"
        folder = self.research / "segmented"
        evaluation = folder / "evaluation"
        evaluation.mkdir(parents=True)
        protocol = {"protocol_version": "net-reward-segmented-v2", "created_at": "2026-09-22T12:00:00+00:00"}
        (folder / "protocol.json").write_text(json.dumps(protocol))
        result = json.loads((original / "results.json").read_text())
        groups = []
        for period in ("development", "holdout"):
            runs = [r for r in result["runs"] if r["period"] == period]
            groups.append({"name": period, "start": runs[0]["start"], "end": runs[0]["end"], "runs": runs,
                           "benchmarks": {"base": {"cash": {"performance": {"net_profit": "0"}}}}})
        (evaluation / "results.json").write_text(json.dumps({"protocol_sha256": hashlib.sha256((folder / "protocol.json").read_bytes()).hexdigest(), "segments": groups, "screen_passed": False}))
        shutil.copyfile(original / "research.sqlite3", evaluation / "research.sqlite3")
        shutil.copyfile(original / "report.md", evaluation / "report.md")
        segmented = next(s for s in self.store.catalog()[0] if s["segmented"])
        self.assertEqual(len(segmented["groups"]), 2)
        self.assertEqual(segmented["groups"][0]["benchmarks"]["base"]["cash"]["performance"]["net_profit"], "0")
        first = self.store.run(segmented["groups"][0]["runs"][0]["id"])
        second = self.store.run(segmented["groups"][1]["runs"][0]["id"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["initial_capital"], second["initial_capital"])
        self.assertEqual(first["performance"]["trades"], 1)
        self.assertEqual(second["performance"]["trades"], 0)

    def test_unknown_id_and_invalid_filters_never_become_file_or_sql_access(self):
        for value in ("../../experiment/research.sqlite3", "' OR 1=1 --", "unknown"):
            with self.assertRaises(KeyError):
                self.store.run(value)
        for outcome in ("anything", "' OR 1=1 --"):
            with self.assertRaises(ValueError):
                self.store.trades(self.run_id, 0, outcome)
        with self.assertRaises(ValueError):
            self.store.signals(self.run_id, -1, "all", "ALL")

    def test_blocked_research_has_a_report_but_no_fabricated_runs(self):
        folder = self.research / "blocked"
        folder.mkdir()
        protocol = {"protocol_version": "slow-timeframe-gated-v1", "created_at": "2026-09-22T23:00:00+00:00"}
        (folder / "protocol.json").write_text(json.dumps(protocol))
        (folder / "report.md").write_text("Data gaps prevent evaluation.")
        blocked = {"schema_version": 1, "status": "blocked_data_quality",
                   "protocol_sha256": hashlib.sha256((folder / "protocol.json").read_bytes()).hexdigest(),
                   "title": "Four hours", "message": "No performance calculated; holdout reserved."}
        (folder / "blocked.json").write_text(json.dumps(blocked))
        before = snapshot(self.research)
        study = next(s for s in self.store.catalog()[0] if s.get("blocked"))
        self.assertTrue(study["blocked"])
        self.assertEqual(study["groups"], [])
        self.assertIsNone(study["screen_passed"])
        self.assertEqual(study["timeframe_label"], "4 Stunden")
        self.assertIn(b"Data gaps", self.store.report(study["id"]))
        with self.assertRaises(KeyError):
            self.store.run(study["id"])
        self.assertEqual(before, snapshot(self.research))
        review_text = "Original trade controls confirm empty intervals."
        (folder / "source-review.md").write_text(review_text)
        (folder / "source-review.json").write_text(json.dumps({
            "blocked_sha256": hashlib.sha256((folder / "blocked.json").read_bytes()).hexdigest(),
            "report_sha256": hashlib.sha256(review_text.encode()).hexdigest(), "message": "Reviewed: empty intervals."}))
        reviewed = next(s for s in self.store.catalog()[0] if s.get("blocked"))
        self.assertEqual(reviewed["finding_note"], "Reviewed: empty intervals.")
        self.assertEqual(self.store.report(reviewed["id"]).decode(), review_text)
        (folder / "evaluation").mkdir()
        self.assertTrue(any(s.get("unavailable") for s in self.store.catalog()[0]))

    def test_annual_results_require_completion_receipt_and_preserve_timeframe(self):
        original = self.research / "experiment"
        folder = self.research / "annual"
        evaluation = folder / "evaluation"
        evaluation.mkdir(parents=True)
        protocol = {"protocol_version": "slow-observed-gated-v2", "created_at": "2026-09-22T23:00:00+00:00"}
        (folder / "protocol.json").write_text(json.dumps(protocol))
        result = json.loads((original / "results.json").read_text())
        runs = result["runs"][:2]
        data = {"protocol_sha256": hashlib.sha256((folder / "protocol.json").read_bytes()).hexdigest(),
                "screen_passed": False, "holdout_note": "2025 remains reserved.",
                "segments": [{"name": "2023", "start": runs[0]["start"], "end": runs[0]["end"], "runs": runs}]}
        (evaluation / "results.json").write_text(json.dumps(data))
        (evaluation / "completion.json").write_text(json.dumps({"results_sha256": hashlib.sha256((evaluation / "results.json").read_bytes()).hexdigest()}))
        shutil.copyfile(original / "research.sqlite3", evaluation / "research.sqlite3")
        shutil.copyfile(original / "report.md", evaluation / "report.md")
        study = next(s for s in self.store.catalog()[0] if s.get("default_cost") == "kraken_current")
        self.assertEqual(study["timeframe_label"], "4 Stunden")
        self.assertEqual(study["default_cost"], "kraken_current")
        self.assertEqual(len(study["cost_names"]), 4)
        self.assertIn("2025 remains reserved", study["finding_note"])
        self.store.run(study["groups"][0]["runs"][0]["id"])
        (evaluation / "completion.json").write_text('{"results_sha256":"changed"}')
        self.assertTrue(any(s.get("unavailable") for s in self.store.catalog()[0]))

    def test_completed_derivative_study_is_report_only_without_fake_sqlite_journal(self):
        folder = self.research / "derivative"
        evaluation = folder / "evaluation"
        evaluation.mkdir(parents=True)
        protocol = {"protocol_version": "perpetual-long-bias-holdout-v1",
                    "created_at": "2026-09-23T12:00:00+00:00"}
        (folder / "protocol.json").write_text(json.dumps(protocol))
        result = {"protocol_sha256": hashlib.sha256((folder / "protocol.json").read_bytes()).hexdigest(),
                  "assessment": {"holdout_passed": False}, "runs": []}
        (evaluation / "results.json").write_text(json.dumps(result))
        (evaluation / "report.md").write_text("Holdout failed.")
        (evaluation / "completion.json").write_text(json.dumps({
            "results_sha256": hashlib.sha256((evaluation / "results.json").read_bytes()).hexdigest()}))
        study = next(s for s in self.store.catalog()[0] if s.get("report_only"))
        self.assertEqual(study["quote_label"], "USD")
        self.assertFalse(study["screen_passed"])
        self.assertEqual(study["groups"], [])
        self.assertEqual(self.store.report(study["id"]), b"Holdout failed.")
        with self.assertRaises(KeyError):
            self.store.run(study["id"])

    def test_dual_horizon_tsmom_is_a_supported_derivative_report(self):
        folder = self.research / "tsmom"
        evaluation = folder / "evaluation"
        evaluation.mkdir(parents=True)
        protocol = {"protocol_version": "perpetual-dual-horizon-tsmom-development-v1",
                    "created_at": "2026-09-24T05:00:00+00:00"}
        (folder / "protocol.json").write_text(json.dumps(protocol))
        result = {"protocol_sha256": hashlib.sha256((folder / "protocol.json").read_bytes()).hexdigest(),
                  "assessment": {"screen_passed": False, "selected": None}, "runs": []}
        (evaluation / "results.json").write_text(json.dumps(result))
        (evaluation / "report.md").write_text("TSMOM screen failed.")
        (evaluation / "completion.json").write_text(json.dumps({
            "results_sha256": hashlib.sha256((evaluation / "results.json").read_bytes()).hexdigest()}))
        study = next(s for s in self.store.catalog()[0]
                     if s.get("title") == "Perpetual: duales Zeitreihen-Momentum")
        self.assertTrue(study["report_only"])
        self.assertFalse(study["screen_passed"])
        self.assertIn("keine Handelsfreigabe", study["finding_note"])

    def test_short_horizon_tsmom_is_a_supported_derivative_report(self):
        folder = self.research / "short-tsmom"
        evaluation = folder / "evaluation"
        evaluation.mkdir(parents=True)
        protocol = {"protocol_version": "perpetual-short-horizon-tsmom-development-v1",
                    "created_at": "2026-09-24T06:00:00+00:00"}
        (folder / "protocol.json").write_text(json.dumps(protocol))
        result = {"protocol_sha256": hashlib.sha256((folder / "protocol.json").read_bytes()).hexdigest(),
                  "assessment": {"screen_passed": False, "selected": None}, "runs": []}
        (evaluation / "results.json").write_text(json.dumps(result))
        (evaluation / "report.md").write_text("Short momentum screen failed.")
        (evaluation / "completion.json").write_text(json.dumps({
            "results_sha256": hashlib.sha256((evaluation / "results.json").read_bytes()).hexdigest()}))
        study = next(s for s in self.store.catalog()[0]
                     if s.get("title") == "Perpetual: kurzfristiges Zeitreihen-Momentum")
        self.assertTrue(study["report_only"])
        self.assertFalse(study["screen_passed"])
        self.assertIn("keine Handelsfreigabe", study["finding_note"])

    def test_regime_confirmed_momentum_is_a_supported_derivative_report(self):
        folder = self.research / "regime-momentum"
        evaluation = folder / "evaluation"
        evaluation.mkdir(parents=True)
        protocol = {"protocol_version": "perpetual-regime-confirmed-momentum-development-v1",
                    "created_at": "2026-09-24T14:05:36+00:00"}
        (folder / "protocol.json").write_text(json.dumps(protocol))
        result = {"protocol_sha256": hashlib.sha256((folder / "protocol.json").read_bytes()).hexdigest(),
                  "assessment": {"screen_passed": False, "selected": None}, "runs": []}
        (evaluation / "results.json").write_text(json.dumps(result))
        (evaluation / "report.md").write_text("Regime momentum screen failed.")
        (evaluation / "completion.json").write_text(json.dumps({
            "results_sha256": hashlib.sha256((evaluation / "results.json").read_bytes()).hexdigest()}))
        study = next(s for s in self.store.catalog()[0]
                     if s.get("title") == "Perpetual: regimebestätigtes Momentum")
        self.assertTrue(study["report_only"])
        self.assertFalse(study["screen_passed"])
        self.assertIn("keine Handelsfreigabe", study["finding_note"])

    def test_corrupt_or_external_artifacts_are_unavailable(self):
        (self.research / "outside").symlink_to(self.root / "dataset", target_is_directory=True)
        (self.root / "dataset/results.json").write_text("{}")
        entries = self.store.catalog()[0]
        self.assertEqual(sum(bool(s.get("unavailable")) for s in entries), 1)
        path = self.research / "experiment/protocol.json"
        path.write_text(path.read_text() + "\n")
        self.assertTrue(all(s.get("unavailable") for s in self.store.catalog()[0]))

    def test_mismatched_database_and_report_do_not_show_fake_numbers(self):
        path = self.research / "experiment/results.json"
        result = json.loads(path.read_text())
        result["runs"][0]["performance"]["net_profit"] = "999999"
        path.write_text(json.dumps(result))
        with self.assertRaises(ValueError):
            self.store.run(self.run_id)

    def test_http_routes_headers_and_mutation_rejection(self):
        before = snapshot(self.research)
        for path, content in (("/", b"Forschungs"), ("/style.css", b":root"), ("/app.js", b"loadCatalog"), ("/api/catalog", b"studies"), ("/api/run?run=" + self.run_id, b"equity")):
            status, headers, body = request(self.store, path)
            self.assertEqual(status, 200)
            self.assertIn(content, body)
            self.assertIn(b"Content-Security-Policy", headers)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(request(self.store, "/api/run", method=method)[0], 405)
        self.assertEqual(request(self.store, "/../../pyproject.toml")[0], 404)
        self.assertEqual(request(self.store, f"/api/trades?run={self.run_id}&page=no")[0], 400)
        self.assertEqual(request(self.store, method="HEAD")[2], b"")
        self.assertEqual(snapshot(self.research), before)

    def test_cross_site_and_unexpected_hosts_are_rejected(self):
        self.assertEqual(request(self.store, host="attacker.example:8765")[0], 403)
        self.assertEqual(request(self.store, headers="Origin: https://attacker.example\r\n")[0], 403)
        self.assertEqual(request(self.store, headers="Sec-Fetch-Site: cross-site\r\n")[0], 403)
        self.assertEqual(request(self.store, host="localhost:8765")[0], 200)


class EquityCompressionTests(unittest.TestCase):
    def test_extremes_and_endpoints_are_preserved_in_order(self):
        rows = [{"timestamp": str(i), "value": str(1000 - i % 20)} for i in range(10000)]
        rows[1234]["value"] = "800"
        rows[8777]["value"] = "1200"
        compressed = compress_equity(rows)
        self.assertLess(len(compressed), 400)
        self.assertEqual(compressed[0], rows[0])
        self.assertEqual(compressed[-1], rows[-1])
        self.assertIn(rows[1234], compressed)
        self.assertIn(rows[8777], compressed)
        self.assertEqual([int(r["timestamp"]) for r in compressed], sorted(int(r["timestamp"]) for r in compressed))

    def test_empty_research_does_not_create_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "does-not-exist"
            self.assertEqual(ResearchStore(path).catalog(), ([], {}))
            self.assertFalse(path.exists())
