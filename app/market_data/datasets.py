"""Local dataset bundles with provenance, checksums and chronological holdouts."""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.market_data.candles import load_candles, write_candles
from app.market_data.models import Candle, TIMEFRAMES
from app.market_data.quality import QualityReport, audit_candles


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def save_dataset(target: Path, candles: tuple[Candle, ...], *, symbol: str, timeframe: str,
                 start: datetime, end: datetime, raw: bytes, source: dict[str, Any],
                 captured_at: datetime) -> QualityReport:
    """Persist also incomplete downloads for inspection; never mark them ready.

    A manifest is written last, so an interrupted write cannot be loaded as a
    complete dataset. Existing directories are never overwritten.
    """
    report = audit_candles(candles, symbol, timeframe, start, end, as_of=captured_at)
    target.mkdir(parents=True, exist_ok=False)
    try:
        (target / "source.raw").write_bytes(raw)
        write_candles(target / "candles.csv", candles)
        write_json(target / "quality.json", report.as_dict())
        hashes = {name: sha256((target / name).read_bytes())
                  for name in ("source.raw", "candles.csv", "quality.json")}
        write_json(target / "manifest.json", {
            "schema_version": 1, "normalizer_version": "1", "market_type": "spot",
            "symbol": symbol, "timeframe": timeframe, "timezone": "UTC",
            "timestamp_semantics": "interval_open", "end_semantics": "exclusive",
            "start": report.start, "end": report.end_exclusive,
            "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
            "source": source, "sha256": hashes, "ready": report.ready,
        })
    except BaseException:
        shutil.rmtree(target)
        raise
    return report


def load_dataset(target: Path) -> tuple[tuple[Candle, ...], dict[str, Any]]:
    """Verify file integrity and coverage before returning backtest-ready data."""
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("market_type") != "spot" or manifest.get("ready") is not True):
        raise ValueError("Dataset is incomplete or has an unsupported manifest")
    if (not isinstance(manifest.get("symbol"), str)
            or not isinstance(manifest.get("timeframe"), str)
            or manifest["timeframe"] not in TIMEFRAMES
            or not isinstance(manifest.get("start"), str)
            or not isinstance(manifest.get("end"), str)):
        raise ValueError("Invalid dataset metadata")
    hashes = manifest.get("sha256", {})
    if not isinstance(hashes, dict) or set(hashes) != {"source.raw", "candles.csv", "quality.json"}:
        raise ValueError("Dataset manifest must hash all expected files")
    for name, expected in hashes.items():
        if sha256((target / name).read_bytes()) != expected:
            raise ValueError(f"Dataset checksum mismatch: {name}")
    try:
        candles = load_candles(target / "candles.csv", manifest["symbol"], manifest["timeframe"])
        report = audit_candles(candles, manifest["symbol"], manifest["timeframe"],
                               datetime.fromisoformat(manifest["start"]), datetime.fromisoformat(manifest["end"]))
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid dataset metadata") from exc
    if not report.ready:
        raise ValueError("Dataset fails coverage or timestamp validation")
    return candles, manifest


def split_dataset(source: Path, target: Path, at: datetime) -> tuple[int, int]:
    """Separate earlier development data and later holdout data, never shuffle."""
    candles, manifest = load_dataset(source)
    if at.tzinfo is None or at.utcoffset() is None or at.microsecond or int(at.timestamp()) % TIMEFRAMES[manifest["timeframe"]]:
        raise ValueError("Split time must be timezone-aware and on an interval boundary")
    development = tuple(c for c in candles if c.closed_at <= at)
    holdout = tuple(c for c in candles if c.timestamp >= at)
    if not development or not holdout or len(development) + len(holdout) != len(candles):
        raise ValueError("Split must leave nonempty, disjoint development and holdout sets")
    target.mkdir(parents=True, exist_ok=False)
    try:
        write_candles(target / "development.csv", development)
        write_candles(target / "holdout.csv", holdout)
        write_json(target / "split.json", {
            "schema_version": 1, "split_at": at.astimezone(timezone.utc).isoformat(),
            "source_manifest_sha256": sha256((source / "manifest.json").read_bytes()),
            "source_candles_sha256": manifest["sha256"]["candles.csv"],
            "symbol": manifest["symbol"], "timeframe": manifest["timeframe"],
            "development_rows": len(development), "holdout_rows": len(holdout),
            "sha256": {name: sha256((target / name).read_bytes())
                       for name in ("development.csv", "holdout.csv")},
            "note": "Chronological separation only; no optimization or performance evaluation performed.",
        })
    except BaseException:
        shutil.rmtree(target)
        raise
    return len(development), len(holdout)
