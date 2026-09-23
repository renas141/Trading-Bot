"""Verified local bundles from Kraken Futures public trade/mark candle payloads."""

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.market_data.candles import load_candles, write_candles
from app.market_data.datasets import write_json
from app.market_data.models import Candle
from app.market_data.quality import audit_candles

DOCUMENTATION = "https://docs.kraken.com/api/docs/futures-api/charts/candles"
ALLOWED_MARKET = "PF_XBTUSD"
ALLOWED_KINDS = ("trade", "mark")


def parse_payload(raw: bytes, kind: str, start: datetime, end: datetime, *,
                  allow_more: bool = False) -> tuple[Candle, ...]:
    if kind not in ALLOWED_KINDS or start >= end:
        raise ValueError("Invalid futures candle request")
    try:
        payload = json.loads(raw)
        rows = payload["candles"]
        if (payload.get("more_candles") not in (False, True)
                or (payload["more_candles"] is True and not allow_more)
                or not isinstance(rows, list)):
            raise ValueError("Payload is partial or malformed")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("Invalid Kraken Futures payload") from exc
    candles: dict[datetime, Candle] = {}
    for row in rows:
        try:
            stamp = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc)
            if not start <= stamp < end:
                continue
            candle = Candle(
                "BTC/USD", "4h", stamp,
                *(Decimal(str(row[name])) for name in ("open", "high", "low", "close", "volume")),
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError(f"Malformed {kind} candle") from exc
        if stamp in candles and candles[stamp] != candle:
            raise ValueError(f"Conflicting duplicate {kind} candle")
        candles[stamp] = candle
    return tuple(candles[stamp] for stamp in sorted(candles))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dataset(output: Path, trade_files: list[Path], mark_files: list[Path],
                  start: datetime, end: datetime) -> dict:
    if output.exists() or not trade_files or not mark_files:
        raise ValueError("Use a new output directory and both trade and mark inputs")
    trade = tuple(c for path in trade_files
                  for c in parse_payload(path.read_bytes(), "trade", start, end, allow_more=True))
    mark = tuple(c for path in mark_files
                 for c in parse_payload(path.read_bytes(), "mark", start, end, allow_more=True))
    trade = tuple({c.timestamp: c for c in trade}[stamp] for stamp in sorted({c.timestamp for c in trade}))
    mark = tuple({c.timestamp: c for c in mark}[stamp] for stamp in sorted({c.timestamp for c in mark}))
    trade_report = audit_candles(trade, "BTC/USD", "4h", start, end)
    mark_report = audit_candles(mark, "BTC/USD", "4h", start, end)
    timestamps_match = tuple(c.timestamp for c in trade) == tuple(c.timestamp for c in mark)
    ready = trade_report.ready and mark_report.ready and timestamps_match
    output.mkdir(parents=True, exist_ok=False)
    try:
        raw_dir = output / "raw"
        raw_dir.mkdir()
        for kind, files in (("trade", trade_files), ("mark", mark_files)):
            for index, source in enumerate(files):
                shutil.copyfile(source, raw_dir / f"{kind}-{index:02}.json")
        write_candles(output / "trade.csv", trade)
        write_candles(output / "mark.csv", mark)
        quality = {"trade": trade_report.as_dict(), "mark": mark_report.as_dict(),
                   "timestamps_match": timestamps_match, "ready": ready}
        write_json(output / "quality.json", quality)
        files = sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file())
        write_json(output / "manifest.json", {
            "schema_version": 1,
            "market_type": "linear_perpetual",
            "market_id": ALLOWED_MARKET,
            "symbol": "BTC/USD",
            "timeframe": "4h",
            "timestamp_semantics": "interval_open",
            "end_semantics": "exclusive",
            "start": start.astimezone(timezone.utc).isoformat(),
            "end": end.astimezone(timezone.utc).isoformat(),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "source": {"provider": "Kraken Futures", "documentation": DOCUMENTATION,
                       "tick_types": list(ALLOWED_KINDS), "funding": "not_included"},
            "sha256": {name: _hash(output / name) for name in files},
            "ready": ready,
        })
    except BaseException:
        shutil.rmtree(output)
        raise
    return quality


def load_futures_dataset(path: Path) -> tuple[tuple[Candle, ...], tuple[Candle, ...], dict]:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != 1 or manifest.get("market_type") != "linear_perpetual"
            or manifest.get("market_id") != ALLOWED_MARKET or manifest.get("ready") is not True):
        raise ValueError("Derivative dataset is not ready")
    hashes = manifest.get("sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Derivative dataset has no checksums")
    for name, expected in hashes.items():
        if _hash(path / name) != expected:
            raise ValueError(f"Derivative dataset checksum mismatch: {name}")
    trade = load_candles(path / "trade.csv", "BTC/USD", "4h")
    mark = load_candles(path / "mark.csv", "BTC/USD", "4h")
    if tuple(c.timestamp for c in trade) != tuple(c.timestamp for c in mark):
        raise ValueError("Trade and mark candles are not aligned")
    return trade, mark, manifest


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp needs an offset")
    return parsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a checked Kraken perpetual dataset")
    parser.add_argument("--trade", type=Path, nargs="+", required=True)
    parser.add_argument("--mark", type=Path, nargs="+", required=True)
    parser.add_argument("--start", type=_timestamp, required=True)
    parser.add_argument("--end", type=_timestamp, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        quality = build_dataset(args.output, args.trade, args.mark, args.start, args.end)
        print(json.dumps(quality, indent=2))
        return 0 if quality["ready"] else 2
    except (OSError, ValueError) as exc:
        print(f"Futures dataset failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
