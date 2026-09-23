"""Import the official headerless Kraken OHLCVT CSV format, without ZIP extraction."""

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal

from app.market_data.models import Candle


def parse_kraken_csv(raw: bytes, symbol: str, timeframe: str,
                     start: datetime, end: datetime) -> tuple[Candle, ...]:
    candles = []
    previous = None
    for number, row in enumerate(csv.reader(io.StringIO(raw.decode("utf-8-sig"))), 1):
        try:
            if len(row) != 7 or not row[0].isdigit() or not row[6].isdigit():
                raise ValueError("Expected timestamp,open,high,low,close,volume,trades without header")
            candle = Candle(symbol, timeframe, datetime.fromtimestamp(int(row[0]), timezone.utc),
                            *(Decimal(value) for value in row[1:6]))
            if previous is not None and candle.timestamp < previous.closed_at:
                raise ValueError("Unsorted or overlapping archive data")
            previous = candle
            if start <= candle.timestamp and candle.closed_at <= end:
                candles.append(candle)
        except (ValueError, ArithmeticError, OverflowError, OSError) as exc:
            raise ValueError(f"Invalid Kraken CSV row {number}") from exc
    return tuple(candles)
