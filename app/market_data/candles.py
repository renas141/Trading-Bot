"""Historical CSV ingestion, with explicit timestamps and Decimal values."""

import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.market_data.models import Candle


def load_candles(path: Path, symbol: str, timeframe: str) -> tuple[Candle, ...]:
    candles = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        if not required.issubset(reader.fieldnames or []) or len(set(reader.fieldnames or [])) != len(reader.fieldnames or []):
            raise ValueError("CSV requires timestamp,open,high,low,close,volume")
        for number, row in enumerate(reader, 2):
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("CSV row width does not match header")
                candle = Candle(
                    symbol=symbol, timeframe=timeframe,
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    **{key: Decimal(row[key]) for key in ("open", "high", "low", "close", "volume")},
                )
            except (ValueError, ArithmeticError, TypeError) as exc:
                raise ValueError(f"Invalid candle at CSV line {number}") from exc
            if candles and candle.timestamp < candles[-1].closed_at:
                raise ValueError(f"Candles must be chronological and non-overlapping (line {number})")
            candles.append(candle)
    if not candles:
        raise ValueError("Historical data must contain at least one candle")
    return tuple(candles)


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    """Write the canonical format without overwriting an existing file."""
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("timestamp", "open", "high", "low", "close", "volume"))
        for candle in candles:
            writer.writerow((candle.timestamp.astimezone(timezone.utc).isoformat(), candle.open,
                             candle.high, candle.low, candle.close, candle.volume))
