"""Local entry point for idle PAPER initialization or historical BACKTEST simulation."""

import argparse
import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import load_settings
from app.database.repository import Repository
from app.domain import TradingMode
from app.errors import TradingBotError
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import PaperBroker
from app.logging_config import configure_logging
from app.market_data.candles import load_candles
from app.market_data.datasets import load_dataset
from app.market_data.quality import require_complete
from app.risk.risk_manager import RejectAllRiskManager
from app.risk.stop_risk import StopRiskManager
from app.strategies.registry import STRATEGIES, make_strategy, strategy_metadata
from backtesting.engine import Backtester
from backtesting.execution import BacktestExecution

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local simulation-only trading foundation")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--strategy", choices=STRATEGIES, default="no_trade",
                        help="Explicit BACKTEST strategy; default no_trade remains inert")
    data_input = parser.add_mutually_exclusive_group()
    data_input.add_argument("--csv", type=Path, help="Historical CSV; requires TRADING_MODE=BACKTEST")
    data_input.add_argument("--dataset", type=Path, help="Verified data bundle; requires TRADING_MODE=BACKTEST")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.env_file)
        if settings.mode != TradingMode.BACKTEST and args.strategy != "no_trade":
            raise ValueError("Research strategies may only be selected in BACKTEST mode")
        if settings.mode == TradingMode.BACKTEST and not (args.csv or args.dataset):
            raise ValueError("BACKTEST requires --csv PATH or --dataset DIRECTORY")
        if settings.mode == TradingMode.PAPER and (args.csv or args.dataset):
            raise ValueError("Historical input requires TRADING_MODE=BACKTEST")
        candles = load_candles(args.csv, settings.symbol, settings.timeframe) if args.csv else ()
        if args.dataset:
            candles, manifest = load_dataset(args.dataset)
            if (manifest["symbol"], manifest["timeframe"]) != (settings.symbol, settings.timeframe):
                raise ValueError("Dataset does not match configured symbol and timeframe")
        if settings.mode == TradingMode.BACKTEST:
            require_complete(candles)
        configure_logging(settings.log_directory, settings.log_level)
        with Repository(settings.database_path) as repository:
            session_id = repository.start_session(settings.mode, settings.initial_capital, settings.symbol)
            try:
                broker = PaperBroker(settings, repository, session_id)
                policy = StopRiskManager(settings) if settings.mode == TradingMode.BACKTEST else RejectAllRiskManager(settings.risk)
                manager = OrderManager(policy, broker, repository, session_id)
                timestamp = candles[0].timestamp if candles else datetime.now(timezone.utc)
                repository.record_equity(session_id, timestamp, settings.initial_capital)
                if settings.mode == TradingMode.BACKTEST:
                    execution = BacktestExecution(manager, broker, repository, session_id)
                    result = Backtester(make_strategy(args.strategy), execution).run(candles)
                    input_path = args.dataset / "candles.csv" if args.dataset else args.csv
                    repository.record_backtest_result(session_id, result, {
                        "execution_model": "cash-long-next-bar-v1", "strategy": strategy_metadata(args.strategy),
                        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                        "fee_rate": settings.paper_fee_rate, "slippage_bps": settings.paper_slippage_bps,
                        "spread_bps": settings.paper_spread_bps, "price_tick": settings.price_tick,
                        "quantity_step": settings.quantity_step, "min_order_notional": settings.min_order_notional,
                        "risk": settings.risk,
                    })
                    print(json.dumps({"session_id": session_id, "performance": result.performance.as_dict()}, indent=2))
                    logger.info("Backtest complete: candles=%d signals=%d trades=%d",
                                result.candles_processed, result.signals_recorded, result.performance.trades)
                else:
                    logger.info("PAPER initialized: virtual capital=%s %s; no strategy or data feed enabled",
                                settings.initial_capital, settings.symbol.split("/")[1])
                repository.finish_session(session_id)
                logger.info("Session STOPPED; LIVE unavailable")
            except BaseException:
                repository.finish_session(session_id, failed=True)
                raise
        return 0
    except (TradingBotError, ValueError, OSError, sqlite3.Error) as exc:
        # Do not print exception payloads, which may include user-supplied secrets.
        logging.getLogger(__name__).error("Startup/run failed (%s). Check configuration, mode, CSV and local paths.",
                                         type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
