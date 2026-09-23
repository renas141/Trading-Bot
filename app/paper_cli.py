"""Bounded public-data PAPER observer, currently NoTrade only; supports resume."""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.config.serialization import decode_settings, encode_settings
from app.config.settings import Settings
from app.database.repository import Repository
from app.errors import MarketDataError, SimulationError
from app.exchange.bitvavo import BitvavoAdapter
from app.execution.durable_paper import DurablePaperBroker
from app.execution.quote_paper import QuotePaperRunner
from app.market_data.datasets import write_json
from app.market_data.models import TIMEFRAMES
from app.market_data.quote_monitor import exclusive_file, publish_summary


def observe(target: Path, *, resume=False, count=3, interval=60, until=None,
            adapter=None, clock=None, pause=time.sleep):
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    until = until or now + timedelta(seconds=count * interval + 60)
    if (type(count) is not int or not 1 <= count <= 10000 or type(interval) is not int
            or not 5 <= interval <= 3600 or until.tzinfo is None or until <= now):
        raise ValueError("Invalid bounded observation schedule")
    if target.exists() and not resume:
        raise ValueError("Output exists; use explicit --resume or choose a new directory")
    if resume and not (target / "session.json").is_file():
        raise ValueError("No resumable session configuration found")
    target.mkdir(parents=True, exist_ok=resume)
    adapter = adapter or BitvavoAdapter()
    with exclusive_file(target / "runner.lock"):
        database = (target / "paper.sqlite3").resolve()
        with Repository(database) as repo:
            if resume:
                saved = json.loads((target / "session.json").read_text())
                if saved["version"] != 1 or saved["strategy"] != "no_trade":
                    raise ValueError("Unsupported PAPER configuration")
                settings = decode_settings(saved["settings"])
                if settings.database_path.resolve() != database:
                    raise ValueError("Configured database path differs from output directory")
                broker = DurablePaperBroker.resume(settings, repo, saved["session_id"])
            else:
                instrument = adapter.instrument()
                if instrument.status != "trading" or instrument.fee_category != "A":
                    raise ValueError("Requires Bitvavo category A trading market")
                settings = Settings(timeframe="4h", database_path=database, paper_fee_rate=Decimal("0.0025"),
                                    paper_slippage_bps=Decimal("5"), paper_spread_bps=Decimal(0),
                                    price_tick=instrument.tick_size, quantity_step=instrument.quantity_step,
                                    min_order_quantity=instrument.minimum_quantity, min_order_notional=instrument.minimum_notional)
                with repo.transaction():
                    session_id = repo.start_session(settings.mode, settings.initial_capital, settings.symbol)
                    broker = DurablePaperBroker(settings, repo, session_id)
                write_json(target / "session.json", {"version": 1, "session_id": broker.session_id,
                           "strategy": "no_trade", "settings": encode_settings(settings),
                           "created_at": clock().isoformat(), "instrument_raw": instrument.raw.decode(),
                           "note": "Observation only, no strategy approved. Public fees are a frozen simulation assumption."})
            runner = QuotePaperRunner(broker, clock=clock)
            attempts, consecutive_errors = 0, 0
            while attempts < count and clock() < until:
                attempts += 1
                try:
                    market = adapter.instrument()
                    seconds = TIMEFRAMES[settings.timeframe]
                    end = datetime.fromtimestamp(int(clock().timestamp()) // seconds * seconds, timezone.utc)
                    start = end - timedelta(seconds=seconds * 302)
                    candles = adapter.download(settings.symbol, settings.timeframe, start, end).candles
                    # Query after downloading closed candles: this quote is the next observed execution reference.
                    book = adapter.book()
                    event = runner.process(book, market, candles)
                    consecutive_errors = 0
                    status = {"status": "observing", "session_id": broker.session_id, "strategy": "no_trade",
                              "last_event": event["timestamp"], "equity": event["equity"], "cash": event["cash"],
                              "open_positions": event["open_positions"], "actions": event["actions"],
                              "attempts_this_process": attempts, "last_error": None}
                except (MarketDataError, ValueError, SimulationError, OSError) as exc:
                    consecutive_errors += 1
                    status = {"status": "degraded", "session_id": broker.session_id, "strategy": "no_trade",
                              "attempts_this_process": attempts, "last_error": str(exc),
                              "consecutive_errors": consecutive_errors, "error_at": clock().isoformat()}
                    with (target / "poll-errors.jsonl").open("a") as handle:
                        handle.write(json.dumps(status) + "\n")
                publish_summary(target / "status.json", status)
                print(f"PAPER observation {attempts}/{count}: {status['status']}; no_trade", flush=True)
                if consecutive_errors >= 5:
                    break
                if attempts < count and clock() < until:
                    pause(min(interval, max(0, (until - clock()).total_seconds())))
            final = {"status": "paused", "session_id": broker.session_id, "strategy": "no_trade",
                     "at": clock().isoformat(), "attempts_this_process": attempts,
                     "consecutive_errors": consecutive_errors, "cash": str(broker.snapshot().cash),
                     "open_positions": len(broker.snapshot().positions), "trades": len(broker.trades),
                     "total_fees": str(broker.total_fees),
                     "note": "Process paused; session remains resumable. NoTrade supplies no entry orders."}
            publish_summary(target / "status.json", final)
            return final


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Bitvavo feed into durable no-trade PAPER observer")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--until", type=datetime.fromisoformat)
    args = parser.parse_args(argv)
    try:
        observe(args.output, resume=args.resume, count=args.count, interval=args.interval, until=args.until)
        return 0
    except (ValueError, MarketDataError, SimulationError, OSError) as exc:
        print(f"PAPER observer failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
