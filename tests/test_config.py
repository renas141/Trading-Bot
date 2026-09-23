import tempfile
import unittest
from pathlib import Path

from app.config.settings import RiskLimits, Settings, load_settings
from app.domain import TradingMode
from app.errors import ConfigurationError, LiveTradingDisabled
from tests.helpers import D


class SettingsTests(unittest.TestCase):
    def test_defaults_need_no_keys(self):
        settings = load_settings(Path("/nonexistent/trading-test.env"), {})
        self.assertEqual(settings.mode, TradingMode.PAPER)
        self.assertFalse(settings.enable_live_trading)

    def test_live_and_enable_flag_fail_closed(self):
        for values in ({"TRADING_MODE": "LIVE"}, {"ENABLE_LIVE_TRADING": "true"},
                       {"TRADING_MODE": "LIVE", "ENABLE_LIVE_TRADING": "false",
                        "KRAKEN_API_KEY": "dummy", "KRAKEN_API_SECRET": "dummy"}):
            with self.subTest(values=values), self.assertRaises(LiveTradingDisabled):
                load_settings(Path("/nonexistent/trading-test.env"), values)
        with self.assertRaises(LiveTradingDisabled):
            Settings(mode=TradingMode.LIVE)

    def test_invalid_values_rejected(self):
        for key, value in (("TRADING_MODE", "bogus"), ("ENABLE_LIVE_TRADING", "yes"),
                           ("MAX_LEVERAGE", "11"), ("MAX_POSITIONS", "0"),
                           ("INITIAL_CAPITAL", "NaN"), ("INITIAL_CAPITAL", "-1"),
                           ("PAPER_FEE_RATE", "Infinity"), ("PAPER_SLIPPAGE_BPS", "10000"),
                           ("MAX_TOTAL_RISK", "0.001"), ("SYMBOL", "BTC/USD")):
            with self.subTest(key=key), self.assertRaises(ConfigurationError):
                load_settings(Path("/nonexistent/trading-test.env"), {key: value})

    def test_env_precedence_and_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('# comment\nINITIAL_CAPITAL="2000"\nTRADING_MODE=BACKTEST\n')
            settings = load_settings(path, {"TRADING_MODE": "PAPER"})
            self.assertEqual(settings.initial_capital, D("2000"))
            self.assertEqual(settings.mode, TradingMode.PAPER)

    def test_malformed_dotenv_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("not a key=value\n")
            with self.assertRaises(ConfigurationError):
                load_settings(path, {})

    def test_absolute_leverage_cap(self):
        self.assertEqual(RiskLimits(max_leverage=D("10")).max_leverage, D("10"))
        with self.assertRaises(ConfigurationError):
            RiskLimits(max_leverage=D("10.01"))
