"""Restartable public PF_XBTUSD regime observation; never accesses an account."""

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
from app.market_data.kraken_perpetual_regime import KINDS, KrakenPerpetualRegimeAdapter
from app.market_data.quote_monitor import exclusive_file, percentile, publish_summary


METRICS = (
    "open_interest", "aggressor_differential", "liquidation_volume",
    "rolling_volatility", "long_short_ratio", "buy_volume", "sell_volume",
    "cumulative_volume_delta",
)


def utcnow():
    return datetime.now(timezone.utc)


def schema(db):
    metric_columns = ",".join(f"{name} TEXT" for name in METRICS)
    db.executescript(f"""
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY, requested_at TEXT NOT NULL, received_at TEXT,
            event_at TEXT, ok INTEGER NOT NULL, {metric_columns}, error TEXT
        );
        CREATE TABLE IF NOT EXISTS raw_responses (
            attempt_id INTEGER NOT NULL REFERENCES attempts(id), kind TEXT NOT NULL,
            url TEXT NOT NULL, raw BLOB NOT NULL, sha256 TEXT NOT NULL,
            PRIMARY KEY(attempt_id, kind)
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
    for row in valid:
        evidence = list(db.execute(
            "SELECT kind,raw,sha256 FROM raw_responses WHERE attempt_id=? ORDER BY kind", (row["id"],)
        ))
        if ({entry["kind"] for entry in evidence} != set(KINDS)
                or len(evidence) != len(KINDS)
                or any(not isinstance(entry["raw"], bytes)
                       or sha256(entry["raw"]) != entry["sha256"] for entry in evidence)):
            raise ValueError("Regime observation evidence is incomplete or corrupt")
    config_row = db.execute("SELECT value FROM metadata WHERE key='configuration'").fetchone()
    configuration = json.loads(config_row[0]) if config_row else {}
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
        "metrics": {
            name: _stats([Decimal(row[name]) for row in valid]) for name in METRICS
        },
        "max_local_request_seconds": max(request_seconds) if request_seconds else None,
        "max_analytics_bucket_age_seconds": max(ages) if ages else None,
        "max_gap_between_successful_receipts_seconds": max(gaps) if gaps else None,
        "raw_integrity_checked": True,
        "exchange_analytics_timestamp_available": True,
        "activation": {"strategy_selected": False, "paper_enabled": False, "live_enabled": False},
        "limitations": [
            "The collector creates prospective research data and no trading signal.",
            "Analytics definitions and availability can change and are revalidated on every sample.",
            "A short observation cannot establish predictive value or profitability.",
            "No credentials, account access, simulated orders or real orders are used.",
        ],
    }


def observe(target, *, count, interval, until, adapter=None, clock=utcnow, pause=time.sleep):
    if not 1 <= count <= 10000 or not 60 <= interval <= 3600 or until.tzinfo is None:
        raise ValueError("Use 1..10000 attempts, 60..3600-second spacing and a timezone-aware deadline")
    if until <= clock():
        raise ValueError("Observation deadline already passed")
    adapter = adapter or KrakenPerpetualRegimeAdapter()
    target.mkdir(parents=True, exist_ok=True)
    with exclusive_file(target / "collector.lock"), closing(sqlite3.connect(target / "observations.sqlite3")) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        schema(db)
        configuration = json.dumps({
            "version": 1, "count": count, "interval_seconds": interval,
            "until": until.isoformat(), "market": "PF_XBTUSD", "provider": "Kraken Futures",
            "analytics_interval_seconds": 60, "metrics": list(METRICS),
        }, sort_keys=True)
        existing = db.execute("SELECT value FROM metadata WHERE key='configuration'").fetchone()
        if existing and existing[0] != configuration:
            raise ValueError("Observation configuration changed; choose a new directory")
        if not existing:
            with db:
                db.execute("INSERT INTO metadata VALUES ('configuration', ?)", (configuration,))
        while db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] < count and clock() < until:
            attempted = clock()
            snapshot = None
            try:
                snapshot = adapter.snapshot()
                metric_values = snapshot.metrics()
                values = (snapshot.requested_at.isoformat(), snapshot.received_at.isoformat(),
                          snapshot.event_at.isoformat(), 1,
                          *(str(metric_values[name]) for name in METRICS), None)
            except (MarketDataError, ValueError, OSError) as exc:
                values = (attempted.isoformat(), clock().isoformat(), None, 0,
                          *(None for _ in METRICS), type(exc).__name__)
            columns = "requested_at,received_at,event_at,ok," + ",".join(METRICS) + ",error"
            markers = ",".join("?" for _ in values)
            with db:
                cursor = db.execute(f"INSERT INTO attempts ({columns}) VALUES ({markers})", values)
                if snapshot is not None:
                    db.executemany(
                        "INSERT INTO raw_responses VALUES (?,?,?,?,?)",
                        [(cursor.lastrowid, kind, snapshot.urls[kind], snapshot.raw[kind],
                          sha256(snapshot.raw[kind])) for kind in KINDS],
                    )
            report = summarize(db, status="collecting")
            publish_summary(target / "summary.json", report)
            print(f"Regime observation {report['attempts']}/{count}: "
                  f"{report['successful']} successful, {report['failed']} failed", flush=True)
            if report["attempts"] < count:
                remaining = (until - clock()).total_seconds()
                if remaining > 0:
                    elapsed = (clock() - attempted).total_seconds()
                    if elapsed < 0:
                        raise ValueError("Local clock moved backwards during observation")
                    pause(min(max(0.0, interval - elapsed), remaining))
        report = summarize(db, status="completed")
        publish_summary(target / "summary.json", report)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Observe public PF_XBTUSD regime analytics")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--until", type=datetime.fromisoformat, required=True)
    args = parser.parse_args(argv)
    try:
        observe(args.output, count=args.count, interval=args.interval, until=args.until)
        return 0
    except (ValueError, MarketDataError, OSError, sqlite3.Error) as exc:
        print(f"Regime observation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
