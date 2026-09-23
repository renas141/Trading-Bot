"""Reconcile an archive gap with raw public trades and adjacent control candles."""

import argparse
import csv
import io
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.market_data.candles import load_candles
from app.market_data.datasets import sha256, write_json
from app.market_data.quality import audit_candles
from app.market_data.trade_history import aggregate_4h, load_evidence


def reconcile(dataset: Path, evidence: Path, gap_start: datetime) -> dict:
    """No dataset mutation. Empty trade intervals remain explicit, never price-filled."""
    gap_end = gap_start + timedelta(hours=4)
    manifest = json.loads((dataset / "manifest.json").read_text())
    if (manifest.get("schema_version") != 1 or manifest.get("market_type") != "spot"
            or manifest.get("symbol") != "BTC/EUR" or manifest.get("timeframe") != "4h"
            or set(manifest.get("sha256", {})) != {"candles.csv", "quality.json", "source.raw"}
            or manifest["source"].get("format") != "official-multipart-ohlcvt-zip-member"):
        raise ValueError("Requires original Kraken BTC/EUR 4h archive bundle")
    for name, expected in manifest["sha256"].items():
        if sha256((dataset / name).read_bytes()) != expected:
            raise ValueError("Archive checksum mismatch")
    candles = load_candles(dataset / "candles.csv", "BTC/EUR", "4h")
    quality = audit_candles(candles, "BTC/EUR", "4h", datetime.fromisoformat(manifest["start"]), datetime.fromisoformat(manifest["end"]))
    if quality.errors or not any(g["start"] == gap_start.isoformat() and g["end_exclusive"] == gap_end.isoformat() for g in quality.gaps):
        raise ValueError("Requested interval is not a single verified archive gap")
    trades, source = load_evidence(evidence)
    if (datetime.fromisoformat(source["start"]) != gap_start - timedelta(hours=4)
            or datetime.fromisoformat(source["end"]) != gap_end + timedelta(hours=4)):
        raise ValueError("Trade evidence must cover the gap and both full adjacent controls")
    # Conservatively require consecutive IDs across the entire requested window.
    ids_contiguous = all(b.id == a.id + 1 for a, b in zip(trades, trades[1:]))
    by_time = {c.timestamp: c for c in candles}
    raw_counts = {int(r[0]): int(r[6]) for r in csv.reader(io.StringIO((dataset / "source.raw").read_text()))}
    controls = []
    for start in (gap_start - timedelta(hours=4), gap_end):
        end = start + timedelta(hours=4)
        selected = tuple(t for t in trades if Decimal(int(start.timestamp())) <= t.timestamp < Decimal(int(end.timestamp())))
        rebuilt = aggregate_4h(selected, start, end)[0]
        original = by_time[start]
        prices_match = all(getattr(rebuilt, field) == getattr(original, field) for field in ("open", "high", "low", "close"))
        # Archive sums can contain sub-satoshi binary floating point residue.
        # Bound the difference to less than half of 1e-8 BTC; do not relax prices/counts.
        volume_difference = abs(rebuilt.volume - original.volume)
        checks = {"ohlc_exact": prices_match, "trade_count_exact": len(selected) == raw_counts[int(start.timestamp())],
                  "volume_within_half_satoshi": volume_difference < Decimal("0.000000005")}
        controls.append({"timestamp": start.isoformat(), "checks": checks, "trades": len(selected),
                         "volume_difference_btc": str(volume_difference),
                         "archive_candle": asdict(original), "reconstructed_candle": asdict(rebuilt)})
    in_gap = tuple(t for t in trades if Decimal(int(gap_start.timestamp())) <= t.timestamp < Decimal(int(gap_end.timestamp())))
    before = [t for t in trades if t.timestamp < Decimal(int(gap_start.timestamp()))]
    after = [t for t in trades if t.timestamp >= Decimal(int(gap_end.timestamp()))]
    controls_passed = all(all(c["checks"].values()) for c in controls)
    if not controls_passed or not ids_contiguous or not before or not after:
        classification = "unresolved_source_disagreement"
    elif in_gap:
        classification = "reconstructable_from_public_trades"
    else:
        classification = "empty_in_public_trade_history"
    return {"classification": classification, "gap_start": gap_start.isoformat(), "gap_end": gap_end.isoformat(),
            "trades_in_gap": len(in_gap), "trade_ids_contiguous": ids_contiguous, "controls_passed": controls_passed,
            "last_trade_before": asdict(before[-1]) if before else None, "first_trade_after": asdict(after[0]) if after else None,
            "controls": controls, "archive_manifest_sha256": sha256((dataset / "manifest.json").read_bytes()),
            "evidence_manifest_sha256": sha256((evidence / "manifest.json").read_bytes()),
            "evidence_directory": str(evidence.resolve()), "public_pages": len(source["pages"]),
            "interpretation": "This describes Kraken's published history, not independently verified exchange availability. Empty intervals must not become executable flat-price candles."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit an archive gap against Kraken public trade evidence")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--gap-start", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = reconcile(args.dataset, args.evidence, args.gap_start)
    write_json(args.output, json.loads(json.dumps(result, default=str)))
    print(result["classification"], "controls_passed=", result["controls_passed"])


if __name__ == "__main__":
    main()
