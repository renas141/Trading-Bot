"""Restartable PF_XBTUSD cost observation; public reads only, never orders."""

import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.errors import MarketDataError
from app.market_data.datasets import sha256
from app.market_data.kraken_perpetual_analytics import (
    NOTIONALS,
    KrakenPerpetualAnalyticsAdapter,
)
from app.market_data.quote_monitor import exclusive_file, percentile, publish_summary


def utcnow():
    return datetime.now(timezone.utc)


def schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY, requested_at TEXT NOT NULL, received_at TEXT,
            event_at TEXT, ok INTEGER NOT NULL, bid TEXT, ask TEXT, spread_bps TEXT,
            funding_relative_rate TEXT, execution_prices_json TEXT, slippage_bps_json TEXT,
            urls_json TEXT, spread_raw BLOB, spread_sha256 TEXT,
            slippage_raw BLOB, slippage_sha256 TEXT, funding_raw BLOB,
            funding_sha256 TEXT, error TEXT
        );
    """)


def _stats(values):
    return {
        "minimum": str(min(values)) if values else None,
        "median_nearest_rank": str(percentile(values, 50)) if values else None,
        "p95_nearest_rank": str(percentile(values, 95)) if values else None,
        "maximum": str(max(values)) if values else None,
    }


def summarize(db, *, status):
    rows = [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY id")]
    valid = [row for row in rows if row["ok"]]
    integrity = all(
        sha256(row[f"{kind}_raw"]) == row[f"{kind}_sha256"]
        for row in valid for kind in ("spread", "slippage", "funding")
    )
    if not integrity:
        raise ValueError("Perpetual observation checksum mismatch")
    config_row = db.execute("SELECT value FROM metadata WHERE key='configuration'").fetchone()
    configuration = json.loads(config_row[0]) if config_row else {}
    spreads = [Decimal(row["spread_bps"]) for row in valid]
    funding = [Decimal(row["funding_relative_rate"]) for row in valid]
    request_seconds = [
        (datetime.fromisoformat(row["received_at"]) - datetime.fromisoformat(row["requested_at"])).total_seconds()
        for row in valid
    ]
    ages = [
        (datetime.fromisoformat(row["received_at"]) - datetime.fromisoformat(row["event_at"])).total_seconds()
        for row in valid
    ]
    gaps = [
        (datetime.fromisoformat(second["received_at"]) - datetime.fromisoformat(first["received_at"])).total_seconds()
        for first, second in zip(valid, valid[1:])
    ]
    slippage = {}
    for side in ("buy", "sell"):
        slippage[side] = {}
        for notional in NOTIONALS:
            key = f"{side}_{notional}"
            values = []
            for row in valid:
                raw_value = json.loads(row["slippage_bps_json"])[key]
                if raw_value is not None:
                    values.append(Decimal(raw_value))
            slippage[side][notional] = {**_stats(values), "available_samples": len(values)}
    return {
        "configuration": configuration,
        "schema_version": 1,
        "provider": "Kraken Futures",
        "market": "PF_XBTUSD",
        "status": status,
        "attempts": len(rows),
        "successful": len(valid),
        "failed": len(rows) - len(valid),
        "first_request": rows[0]["requested_at"] if rows else None,
        "last_request": rows[-1]["requested_at"] if rows else None,
        "spread_bps": _stats(spreads),
        "estimated_adverse_slippage_bps": slippage,
        "signed_relative_funding_rate": {**_stats(funding), "positive_means_longs_pay": True},
        "max_local_request_seconds": max(request_seconds) if request_seconds else None,
        "max_analytics_bucket_age_seconds": max(ages) if ages else None,
        "max_gap_between_successful_receipts_seconds": max(gaps) if gaps else None,
        "raw_integrity_checked": integrity,
        "exchange_analytics_timestamp_available": True,
        "limitations": [
            "A short current observation window is not historical or typical cost evidence.",
            "Analytics buckets and estimated average execution prices do not guarantee a fill.",
            "Funding is the signed close published for the sampled minute, not a reconstructed payment history.",
            "No credentials, account access, simulated orders or real orders are used by this collector.",
        ],
    }


def observe(target, *, count, interval, until, adapter=None, clock=utcnow, pause=time.sleep):
    if not 1 <= count <= 10000 or not 60 <= interval <= 3600 or until.tzinfo is None:
        raise ValueError("Use 1..10000 attempts, 60..3600-second spacing and a timezone-aware deadline")
    if until <= clock():
        raise ValueError("Observation deadline already passed")
    adapter = adapter or KrakenPerpetualAnalyticsAdapter()
    target.mkdir(parents=True, exist_ok=True)
    with exclusive_file(target / "collector.lock"), closing(sqlite3.connect(target / "observations.sqlite3")) as db:
        db.row_factory = sqlite3.Row
        schema(db)
        configuration = json.dumps({
            "version": 1, "count": count, "interval_seconds": interval,
            "until": until.isoformat(), "market": "PF_XBTUSD", "provider": "Kraken Futures",
            "analytics_interval_seconds": 60,
        }, sort_keys=True)
        existing = db.execute("SELECT value FROM metadata WHERE key='configuration'").fetchone()
        if existing and existing[0] != configuration:
            raise ValueError("Observation configuration changed; choose a new directory")
        if not existing:
            with db:
                db.execute("INSERT INTO metadata VALUES ('configuration', ?)", (configuration,))
        while db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] < count and clock() < until:
            attempted = clock()
            try:
                snapshot = adapter.snapshot()
                execution_json = json.dumps({key: str(value) if value is not None else None
                                             for key, value in snapshot.execution_prices.items()}, sort_keys=True)
                slippage_json = json.dumps({key: str(value) if value is not None else None
                                            for key, value in snapshot.slippage_bps.items()}, sort_keys=True)
                values = (
                    snapshot.requested_at.isoformat(), snapshot.received_at.isoformat(),
                    snapshot.event_at.isoformat(), 1, str(snapshot.bid), str(snapshot.ask),
                    str(snapshot.spread_bps), str(snapshot.funding_relative_rate), execution_json,
                    slippage_json, json.dumps(snapshot.urls, sort_keys=True),
                    snapshot.raw["spreads"], sha256(snapshot.raw["spreads"]),
                    snapshot.raw["slippage"], sha256(snapshot.raw["slippage"]),
                    snapshot.raw["funding"], sha256(snapshot.raw["funding"]), None,
                )
            except (MarketDataError, ValueError, OSError) as exc:
                values = (attempted.isoformat(), clock().isoformat(), None, 0, None, None, None,
                          None, None, None, None, None, None, None, None, None, None,
                          type(exc).__name__)
            with db:
                db.execute("""INSERT INTO attempts (
                    requested_at,received_at,event_at,ok,bid,ask,spread_bps,funding_relative_rate,
                    execution_prices_json,slippage_bps_json,urls_json,spread_raw,spread_sha256,
                    slippage_raw,slippage_sha256,funding_raw,funding_sha256,error
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
            report = summarize(db, status="collecting")
            publish_summary(target / "summary.json", report)
            print(f"Perpetual observation {report['attempts']}/{count}: "
                  f"{report['successful']} successful, {report['failed']} failed", flush=True)
            if report["attempts"] < count:
                remaining = (until - clock()).total_seconds()
                if remaining > 0:
                    pause(min(interval, remaining))
        report = summarize(db, status="completed")
        publish_summary(target / "summary.json", report)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded public Kraken Perpetual observations; no orders")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--until", type=datetime.fromisoformat, required=True)
    args = parser.parse_args(argv)
    try:
        observe(args.output, count=args.count, interval=args.interval, until=args.until)
        return 0
    except (ValueError, MarketDataError, OSError) as exc:
        print(f"Perpetual monitor failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
