"""Explicit data commands, separate from the offline paper/backtest runner."""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.errors import MarketDataError
from app.exchange.kraken import KrakenAdapter
from app.market_data.datasets import load_dataset, save_dataset, split_dataset
from app.market_data.kraken_csv import parse_kraken_csv
from app.market_data.models import TIMEFRAMES
from app.market_data.quality import audit_candles
from app.market_data.archive import ARCHIVES, fetch_archive_csv

ARCHIVE_DOC = "https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data"


def timestamp(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Timezone required")
        return stamp.astimezone(timezone.utc)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use ISO-8601 with timezone, e.g. 2026-09-01T00:00:00Z") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only BTC/EUR historical data tools")
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download", help="Download recent closed Kraken Spot candles")
    download.add_argument("--bars", type=int, default=480)
    download.add_argument("--timeframe", choices=TIMEFRAMES, default="15m")
    download.add_argument("--output", type=Path, required=True, help="New dataset directory")
    archive = commands.add_parser("import-kraken", help="Import a local official Kraken OHLCVT CSV")
    archive.add_argument("--csv", type=Path, required=True)
    archive.add_argument("--timeframe", choices=TIMEFRAMES, default="15m")
    archive.add_argument("--start", type=timestamp, required=True)
    archive.add_argument("--end", type=timestamp, required=True)
    archive.add_argument("--output", type=Path, required=True)
    remote_archive = commands.add_parser("download-archive", help="Fetch only BTC/EUR from an official quarterly ZIP")
    remote_archive.add_argument("--quarter", choices=ARCHIVES, required=True)
    remote_archive.add_argument("--timeframe", choices=TIMEFRAMES, default="15m")
    remote_archive.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="Verify checksums, OHLCV validity and full coverage")
    verify.add_argument("dataset", type=Path)
    split = commands.add_parser("split", help="Separate development and holdout periods")
    split.add_argument("dataset", type=Path)
    split.add_argument("--at", type=timestamp, required=True)
    split.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if hasattr(args, "output") and args.output.exists():
            raise ValueError("Output already exists; choose a new directory")
        if args.command == "verify":
            candles, manifest = load_dataset(args.dataset)
            print(f"Verified: {len(candles)} {manifest['symbol']} {manifest['timeframe']} candles; no gaps")
            return 0
        if args.command == "split":
            development, holdout = split_dataset(args.dataset, args.output, args.at)
            print(f"Saved chronological split: development={development}, holdout={holdout}")
            return 0
        now = datetime.now(timezone.utc)
        if args.command == "download":
            if not 1 <= args.bars <= 719:
                raise ValueError("Request 1..719 closed candles; use official CSV archives for longer histories")
            seconds = TIMEFRAMES[args.timeframe]
            end = datetime.fromtimestamp(int(now.timestamp()) // seconds * seconds, timezone.utc)
            start = end - timedelta(seconds=seconds * args.bars)
            fetched = KrakenAdapter().download("BTC/EUR", args.timeframe, start, end)
            candles, raw, captured_at = fetched.candles, fetched.raw, fetched.requested_at
            source = {"provider": "Kraken", "format": "spot-rest-ohlc", "url": fetched.request_url,
                      "retention_limit_rows": 720, "last_uncommitted_row_removed": True}
        elif args.command == "download-archive":
            raw, source, start, end = fetch_archive_csv(args.quarter, args.timeframe)
            captured_at = now
            candles = parse_kraken_csv(raw, "BTC/EUR", args.timeframe, start, end)
        else:
            start, end, captured_at = args.start, args.end, now
            # Check range before reading a potentially large archive CSV.
            audit_candles((), "BTC/EUR", args.timeframe, start, end, as_of=now)
            if end > now:
                raise ValueError("Archive range must not end in the future")
            expected_name = f"XBTEUR_{TIMEFRAMES[args.timeframe] // 60}.csv"
            if args.csv.name != expected_name:
                raise ValueError(f"Expected original Kraken filename {expected_name}; do not relabel another market")
            with args.csv.open("rb") as handle:
                raw = handle.read(100_000_001)
            if len(raw) > 100_000_000:
                raise ValueError("CSV exceeds the current 100 MB import limit")
            candles = parse_kraken_csv(raw, "BTC/EUR", args.timeframe, start, end)
            source = {"provider": "Kraken", "format": "local-ohlcvt-csv",
                      "filename": args.csv.name, "documentation": ARCHIVE_DOC,
                      "provenance": "User-supplied archive file; source authenticity not independently verified"}
        report = save_dataset(args.output, candles, symbol="BTC/EUR", timeframe=args.timeframe,
                              start=start, end=end, raw=raw, source=source, captured_at=captured_at)
        print(json.dumps(report.as_dict(), indent=2))
        print(f"Saved dataset: {args.output}")
        return 0 if report.ready else 2
    except (MarketDataError, ValueError, OSError) as exc:
        # Source bodies are never echoed. No credential environment variables are read.
        message = str(exc) if isinstance(exc, (MarketDataError, ValueError)) else type(exc).__name__
        print(f"Data command failed: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
