"""Read-only Bitvavo dataset collector with bounded pages and original responses."""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app.errors import MarketDataError
from app.exchange.bitvavo import BitvavoAdapter, MAX_BARS
from app.market_data.cli import timestamp
from app.market_data.datasets import save_dataset, sha256, write_json
from app.market_data.models import TIMEFRAMES
from app.market_data.quality import audit_candles

MAX_PAGES = 16
DOCUMENTATION = "https://docs.bitvavo.com/docs/rest-api/get-candlestick-data/"


def collect(target: Path, timeframe: str, start: datetime, end: datetime, *,
            adapter: BitvavoAdapter | None = None, pause: Callable[[float], None] = time.sleep):
    if target.exists():
        raise ValueError("Output already exists")
    audit = audit_candles((), "BTC/EUR", timeframe, start, end)
    if end > datetime.now(timezone.utc) or audit.expected_rows > MAX_PAGES * MAX_BARS:
        raise ValueError("Request must be historical and no larger than 16 pages")
    adapter = adapter or BitvavoAdapter()
    step = timedelta(seconds=TIMEFRAMES[timeframe] * MAX_BARS)
    candles, pages = [], []
    cursor = start
    captured_at = None
    while cursor < end:
        boundary = min(cursor + step, end)
        fetched = adapter.download("BTC/EUR", timeframe, cursor, boundary)
        captured_at = fetched.requested_at
        candles.extend(fetched.candles)
        pages.append({"request_url": fetched.request_url,
                      "requested_at": fetched.requested_at.isoformat(),
                      "start": cursor.isoformat(), "end_exclusive": boundary.isoformat(),
                      "sha256": sha256(fetched.raw), "body_utf8": fetched.raw.decode("utf-8")})
        cursor = boundary
        print(f"Bitvavo page {len(pages)}: {len(fetched.candles)} candles", flush=True)
        if cursor < end:
            pause(1.1)
    raw = json.dumps({"schema_version": 1, "pages": pages}, ensure_ascii=False).encode("utf-8")
    return save_dataset(target, tuple(candles), symbol="BTC/EUR", timeframe=timeframe,
                        start=start, end=end, raw=raw, captured_at=captured_at,
                        source={"provider": "Bitvavo", "format": "public-rest-pages-v1",
                                "documentation": DOCUMENTATION, "pages": len(pages),
                                "page_limit": MAX_BARS, "empty_intervals": "left missing, never filled",
                                "end_semantics": "aligned close boundary; canonical range excludes end"})


def snapshot(target: Path, *, adapter: BitvavoAdapter | None = None) -> None:
    """Persist current instrument and one quote; this is not a spread estimate."""
    if target.exists():
        raise ValueError("Output already exists")
    adapter = adapter or BitvavoAdapter()
    market, book = adapter.instrument(), adapter.book()
    target.mkdir(parents=True, exist_ok=False)
    (target / "instrument.raw").write_bytes(market.raw)
    (target / "book.raw").write_bytes(book.raw)
    write_json(target / "snapshot.json", {
        "schema_version": 1, "provider": "Bitvavo", "market": "BTC-EUR",
        "status": market.status, "tick_size": str(market.tick_size),
        "quantity_step": str(market.quantity_step), "minimum_quantity": str(market.minimum_quantity),
        "minimum_notional": str(market.minimum_notional), "fee_category": market.fee_category,
        "bid": str(book.bid), "ask": str(book.ask), "bid_size": str(book.bid_size),
        "ask_size": str(book.ask_size), "spread_bps": str(book.spread_bps),
        "instrument_requested_at": market.requested_at.isoformat(),
        "book_requested_at": book.requested_at.isoformat(), "book_received_at": book.received_at.isoformat(),
        "exchange_event_timestamp": None,
        "note": "One public top-of-book observation; no historical spread, depth or guaranteed fill inference.",
        "urls": {"instrument": market.request_url, "book": book.request_url},
        "sha256": {"instrument.raw": sha256(market.raw), "book.raw": sha256(book.raw)},
    })


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Bitvavo BTC/EUR data")
    commands = parser.add_subparsers(dest="command", required=True)
    history = commands.add_parser("history")
    history.add_argument("--start", type=timestamp, required=True)
    history.add_argument("--end", type=timestamp, required=True)
    history.add_argument("--timeframe", choices=TIMEFRAMES, default="4h")
    history.add_argument("--output", type=Path, required=True)
    quote = commands.add_parser("snapshot")
    quote.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            snapshot(args.output)
            print(f"Public market snapshot saved: {args.output}")
            return 0
        report = collect(args.output, args.timeframe, args.start, args.end)
        print(json.dumps(report.as_dict(), indent=2))
        return 0 if report.ready else 2
    except (ValueError, MarketDataError, OSError) as exc:
        print(f"Bitvavo data failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
