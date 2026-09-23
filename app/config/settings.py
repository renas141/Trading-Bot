"""Validated settings; LIVE is rejected even when credentials exist."""

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

from app.domain import TradingMode, positive_decimal, validate_symbol
from app.errors import ConfigurationError, LiveTradingDisabled


@dataclass(frozen=True)
class RiskLimits:
    max_leverage: Decimal = Decimal("1")
    max_risk_per_trade: Decimal = Decimal("0.01")
    max_total_risk: Decimal = Decimal("0.03")
    max_daily_loss: Decimal = Decimal("0.03")
    max_drawdown: Decimal = Decimal("0.10")
    max_positions: int = 1
    min_liquidation_distance: Decimal = Decimal("0.10")
    max_position_notional: Decimal = Decimal("1000")
    kill_switch: bool = False

    def __post_init__(self) -> None:
        positive_decimal(self.max_leverage, "max_leverage")
        if not 1 <= self.max_leverage <= 10:
            raise ConfigurationError("max_leverage must be between 1 and 10")
        for name in ("max_risk_per_trade", "max_total_risk", "max_daily_loss",
                     "max_drawdown", "min_liquidation_distance"):
            value = getattr(self, name)
            positive_decimal(value, name)
            if value > 1:
                raise ConfigurationError(f"{name} must be <= 1")
        if self.max_risk_per_trade > self.max_total_risk:
            raise ConfigurationError("Per-trade risk cannot exceed total risk")
        if type(self.max_positions) is not int or self.max_positions < 1:
            raise ConfigurationError("max_positions must be a positive integer")
        positive_decimal(self.max_position_notional, "max_position_notional")
        if type(self.kill_switch) is not bool:
            raise ConfigurationError("kill_switch must be a boolean")


@dataclass(frozen=True)
class Settings:
    mode: TradingMode = TradingMode.PAPER
    enable_live_trading: bool = False
    symbol: str = "BTC/EUR"
    timeframe: str = "15m"
    initial_capital: Decimal = Decimal("1000")
    database_path: Path = Path("data/trading.sqlite3")
    log_directory: Path = Path("logs")
    log_level: str = "INFO"
    paper_fee_rate: Decimal = Decimal("0.0026")
    paper_slippage_bps: Decimal = Decimal("5")
    paper_spread_bps: Decimal = Decimal("0")
    price_tick: Decimal = Decimal("0.01")
    quantity_step: Decimal = Decimal("0.00000001")
    min_order_notional: Decimal = Decimal("5")
    min_order_quantity: Decimal = Decimal("0")
    risk: RiskLimits = field(default_factory=RiskLimits)

    def __post_init__(self) -> None:
        if self.mode == TradingMode.LIVE or self.enable_live_trading is not False:
            raise LiveTradingDisabled("LIVE trading is not implemented and cannot be enabled")
        if not isinstance(self.mode, TradingMode):
            raise ConfigurationError("mode must be a TradingMode")
        validate_symbol(self.symbol)
        if self.symbol != "BTC/EUR":
            raise ConfigurationError("This foundation supports BTC/EUR only")
        if self.timeframe not in {"1m", "5m", "15m", "1h", "4h"}:
            raise ConfigurationError("Unsupported timeframe")
        positive_decimal(self.initial_capital, "initial_capital")
        positive_decimal(self.paper_fee_rate, "paper_fee_rate", allow_zero=True)
        positive_decimal(self.paper_slippage_bps, "paper_slippage_bps", allow_zero=True)
        positive_decimal(self.paper_spread_bps, "paper_spread_bps", allow_zero=True)
        for name in ("price_tick", "quantity_step", "min_order_notional"):
            positive_decimal(getattr(self, name), name)
        positive_decimal(self.min_order_quantity, "min_order_quantity", allow_zero=True)
        if self.paper_fee_rate >= 1 or self.paper_slippage_bps + self.paper_spread_bps / 2 >= 10000:
            raise ConfigurationError("Simulation costs must be below 100%")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("Unsupported log level")


def _boolean(value: str) -> bool:
    if value.lower() not in {"true", "false"}:
        raise ConfigurationError("Boolean settings accept only true or false")
    return value.lower() == "true"


def _dotenv(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE loader, without interpolation or executing shell code."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip().isidentifier():
            raise ConfigurationError(f"Invalid .env syntax at line {number}")
        value = value.strip()
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigurationError(f"Unclosed .env quote at line {number}")
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_settings(env_file: Path = Path(".env"), environ: Mapping[str, str] | None = None) -> Settings:
    values = _dotenv(env_file)
    values.update(os.environ if environ is None else environ)
    defaults = Settings()
    limits = RiskLimits()
    try:
        risk_values = {
            name: Decimal(values.get(name.upper(), str(getattr(limits, name))))
            for name in ("max_leverage", "max_risk_per_trade", "max_total_risk",
                         "max_daily_loss", "max_drawdown", "min_liquidation_distance",
                         "max_position_notional")
        }
        return Settings(
            mode=TradingMode(values.get("TRADING_MODE", "PAPER").upper()),
            enable_live_trading=_boolean(values.get("ENABLE_LIVE_TRADING", "false")),
            symbol=values.get("SYMBOL", defaults.symbol),
            timeframe=values.get("TIMEFRAME", defaults.timeframe),
            initial_capital=Decimal(values.get("INITIAL_CAPITAL", "1000")),
            database_path=Path(values.get("DATABASE_PATH", str(defaults.database_path))),
            log_directory=Path(values.get("LOG_DIRECTORY", str(defaults.log_directory))),
            log_level=values.get("LOG_LEVEL", "INFO").upper(),
            paper_fee_rate=Decimal(values.get("PAPER_FEE_RATE", "0.0026")),
            paper_slippage_bps=Decimal(values.get("PAPER_SLIPPAGE_BPS", "5")),
            paper_spread_bps=Decimal(values.get("PAPER_SPREAD_BPS", "0")),
            price_tick=Decimal(values.get("PRICE_TICK", "0.01")),
            quantity_step=Decimal(values.get("QUANTITY_STEP", "0.00000001")),
            min_order_notional=Decimal(values.get("MIN_ORDER_NOTIONAL", "5")),
            min_order_quantity=Decimal(values.get("MIN_ORDER_QUANTITY", "0")),
            risk=RiskLimits(**risk_values,
                            max_positions=int(values.get("MAX_POSITIONS", "1")),
                            kill_switch=_boolean(values.get("KILL_SWITCH", "false"))),
        )
    except (ValueError, InvalidOperation) as exc:
        # Never echo configuration values: future environment entries may be secrets.
        raise ConfigurationError("Invalid configuration; check setting types and limits") from exc
