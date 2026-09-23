import logging
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.cli import main


class CliTests(unittest.TestCase):
    def tearDown(self):
        # CLI setup replaces root handlers. Remove them before temporary paths vanish.
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()

    def test_paper_start_is_offline_and_session_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"DATABASE_PATH": str(root / "test.sqlite3"), "LOG_DIRECTORY": str(root / "logs"),
                   "KRAKEN_API_KEY": "not-a-real-key", "KRAKEN_API_SECRET": "not-a-real-secret"}
            with patch.dict(os.environ, env, clear=True), patch("socket.socket", side_effect=AssertionError("Network forbidden")):
                self.assertEqual(main(["--env-file", str(root / "missing.env")]), 0)
            with closing(sqlite3.connect(root / "test.sqlite3")) as connection:
                self.assertEqual(connection.execute("SELECT status FROM sessions").fetchone()[0], "STOPPED")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)
            logging.shutdown()
            text = (root / "logs/bot.log").read_text()
            self.assertNotIn("not-a-real-key", text)
            self.assertNotIn("not-a-real-secret", text)

    def test_live_start_rejected_before_creating_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"TRADING_MODE": "LIVE", "ENABLE_LIVE_TRADING": "false", "DATABASE_PATH": str(root / "test.db")}
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(main(["--env-file", str(root / "missing.env")]), 1)
            self.assertFalse((root / "test.db").exists())

    def test_backtest_cli_persists_hold_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "history.csv"
            path.write_text("timestamp,open,high,low,close,volume\n2024-01-01T00:00:00Z,100,110,90,105,2\n")
            env = {"TRADING_MODE": "BACKTEST", "DATABASE_PATH": str(root / "test.db"), "LOG_DIRECTORY": str(root / "logs")}
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(main(["--env-file", str(root / "missing.env"), "--csv", str(path)]), 0)
            with closing(sqlite3.connect(root / "test.db")) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)
            logging.shutdown()

    def test_backtest_needs_a_csv(self):
        with patch.dict(os.environ, {"TRADING_MODE": "BACKTEST"}, clear=True):
            self.assertEqual(main(["--env-file", "/nonexistent/trading-test.env"]), 1)
