"""Bounded, restartable observation of public quotes; never submits orders."""

import argparse
import fcntl
import json
import math
import sqlite3
import sys
import time
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.errors import MarketDataError
from app.exchange.bitvavo import BitvavoAdapter
from app.market_data.datasets import sha256


def utcnow():
    return datetime.now(timezone.utc)


@contextmanager
def exclusive_file(path):
    with path.open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another quote collector owns this observation directory") from None
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY, requested_at TEXT NOT NULL, received_at TEXT,
            ok INTEGER NOT NULL, bid TEXT, ask TEXT, bid_size TEXT, ask_size TEXT,
            spread_bps TEXT, url TEXT, raw BLOB, raw_sha256 TEXT, error TEXT
        );
    """)


def percentile(values, percentage):
    return sorted(values)[max(0, math.ceil(len(values) * percentage / 100) - 1)] if values else None


def summarize(db, *, status):
    rows = [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY id")]
    valid = [r for r in rows if r["ok"]]
    spreads = [Decimal(r["spread_bps"]) for r in valid]
    latencies = [(datetime.fromisoformat(r["received_at"]) - datetime.fromisoformat(r["requested_at"])).total_seconds() for r in valid]
    gaps = [(datetime.fromisoformat(b["received_at"]) - datetime.fromisoformat(a["received_at"])).total_seconds()
            for a, b in zip(valid, valid[1:])]
    integrity = all(sha256(r["raw"]) == r["raw_sha256"] for r in valid)
    if not integrity:
        raise ValueError("Quote observation checksum mismatch")
    config_row = db.execute("SELECT value FROM metadata WHERE key='configuration'").fetchone()
    configuration = json.loads(config_row[0]) if config_row else {}
    return {"configuration": configuration, "schema_version": 1, "provider": "Bitvavo", "market": "BTC-EUR", "status": status,
            "attempts": len(rows), "successful": len(valid), "failed": len(rows) - len(valid),
            "first_request": rows[0]["requested_at"] if rows else None,
            "last_request": rows[-1]["requested_at"] if rows else None,
            "spread_bps": {"minimum": str(min(spreads)) if spreads else None,
                           "median_nearest_rank": str(percentile(spreads, 50)) if spreads else None,
                           "p95_nearest_rank": str(percentile(spreads, 95)) if spreads else None,
                           "maximum": str(max(spreads)) if spreads else None},
            "max_local_request_seconds": max(latencies) if latencies else None,
            "max_gap_between_successful_receipts_seconds": max(gaps) if gaps else None,
            "minimum_top_ask_notional_eur": str(min(Decimal(r["ask"])*Decimal(r["ask_size"]) for r in valid)) if valid else None,
            "minimum_top_bid_notional_eur": str(min(Decimal(r["bid"])*Decimal(r["bid_size"]) for r in valid)) if valid else None,
            "raw_integrity_checked": integrity, "exchange_event_timestamp_available": False,
            "limitations": ["A short sampled observation window, not historical or typical spread evidence.",
                            "Public book lacks exchange-event timestamp; local receipt does not prove quote freshness.",
                            "Top-of-book size is not full depth and does not guarantee an executable fill.",
                            "No fees, account access, simulated orders or real orders are produced by this collector."]}


def publish_summary(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def observe(target, *, count, interval, until, adapter=None, clock=utcnow, pause=time.sleep):
    if not 1 <= count <= 10000 or not 5 <= interval <= 3600 or until.tzinfo is None:
        raise ValueError("Use 1..10000 attempts, 5..3600-second spacing and a timezone-aware deadline")
    if until <= clock():
        raise ValueError("Observation deadline already passed")
    adapter = adapter or BitvavoAdapter()
    target.mkdir(parents=True, exist_ok=True)
    with exclusive_file(target / "collector.lock"), closing(sqlite3.connect(target / "observations.sqlite3")) as db:
        db.row_factory = sqlite3.Row
        schema(db)
        configuration = json.dumps({"version": 1, "count": count, "interval_seconds": interval,
                                    "until": until.isoformat(), "market": "BTC-EUR", "provider": "Bitvavo"}, sort_keys=True)
        existing = db.execute("SELECT value FROM metadata WHERE key='configuration'").fetchone()
        if existing and existing[0] != configuration:
            raise ValueError("Observation configuration changed; choose a new directory")
        if existing:
            evidence = dict(db.execute("SELECT key,value FROM metadata"))
            if sha256(evidence["instrument_raw"].encode()) != evidence["instrument_sha256"]:
                raise ValueError("Instrument evidence checksum mismatch")
        if not existing:
            market = adapter.instrument()
            with db:
                db.execute("INSERT INTO metadata VALUES ('configuration', ?)", (configuration,))
                db.execute("INSERT INTO metadata VALUES ('instrument_raw', ?)", (market.raw.decode(),))
                db.execute("INSERT INTO metadata VALUES ('instrument_sha256', ?)", (sha256(market.raw),))
                db.execute("INSERT INTO metadata VALUES ('instrument_url', ?)", (market.request_url,))
                db.execute("INSERT INTO metadata VALUES ('instrument_requested_at', ?)", (market.requested_at.isoformat(),))
        while db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] < count and clock() < until:
            attempted = clock()
            try:
                quote = adapter.book()
                values = (quote.requested_at.isoformat(), quote.received_at.isoformat(), 1,
                          str(quote.bid), str(quote.ask), str(quote.bid_size), str(quote.ask_size),
                          str(quote.spread_bps), quote.request_url, quote.raw, sha256(quote.raw), None)
            except (MarketDataError, ValueError, OSError) as exc:
                values = (attempted.isoformat(), clock().isoformat(), 0, None, None, None, None, None,
                          None, None, None, type(exc).__name__)
            with db:
                db.execute("INSERT INTO attempts (requested_at,received_at,ok,bid,ask,bid_size,ask_size,spread_bps,url,raw,raw_sha256,error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", values)
            report = summarize(db, status="collecting")
            publish_summary(target / "summary.json", report)
            print(f"Quote observation {report['attempts']}/{count}: {report['successful']} successful, {report['failed']} failed", flush=True)
            if report["attempts"] < count:
                remaining = (until - clock()).total_seconds()
                if remaining > 0:
                    pause(min(interval, remaining))
        report = summarize(db, status="completed")
        publish_summary(target / "summary.json", report)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded public Bitvavo quote observations; no orders")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--until", type=datetime.fromisoformat, required=True)
    args = parser.parse_args(argv)
    try:
        observe(args.output, count=args.count, interval=args.interval, until=args.until)
        return 0
    except (ValueError, MarketDataError, OSError) as exc:
        print(f"Quote monitor failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
