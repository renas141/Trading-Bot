"""Parsing and deterministic 4h alignment for Kraken Futures funding analytics."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal


DOCUMENTATION = "https://docs.kraken.com/api/docs/futures-api/charts/market-analytics"


@dataclass(frozen=True)
class HourlyFundingRate:
    timestamp: datetime
    relative_rate: Decimal

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("Funding timestamp needs a timezone")
        if not isinstance(self.relative_rate, Decimal) or not self.relative_rate.is_finite():
            raise ValueError("Funding rate must be a finite Decimal")


def parse_hourly_funding(raw: bytes, start: datetime, end: datetime, *,
                         allow_more: bool = False) -> tuple[HourlyFundingRate, ...]:
    """Use each hourly bucket's close; retain the sign paid by LONG positions."""
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Invalid funding range")
    try:
        payload = json.loads(raw)
        result = payload["result"]
        timestamps = result["timestamp"]
        rows = result["data"]["relativeRate"]
        if (payload.get("errors") != [] or result.get("more") not in (False, True)
                or (result["more"] is True and not allow_more)
                or not isinstance(timestamps, list) or not isinstance(rows, list)
                or len(timestamps) != len(rows)):
            raise ValueError("Funding payload is partial or malformed")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("Invalid Kraken funding payload") from exc
    points: dict[datetime, HourlyFundingRate] = {}
    for raw_stamp, row in zip(timestamps, rows):
        try:
            stamp = datetime.fromtimestamp(int(raw_stamp) / 1000, timezone.utc)
            if not start <= stamp < end:
                continue
            if not isinstance(row, list) or len(row) != 4:
                raise ValueError("Funding OHLC row must contain four values")
            point = HourlyFundingRate(stamp, Decimal(str(row[3])))
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError("Malformed Kraken funding row") from exc
        if stamp.minute or stamp.second or stamp.microsecond:
            raise ValueError("Funding timestamp is not hourly aligned")
        if stamp in points and points[stamp] != point:
            raise ValueError("Conflicting duplicate funding rate")
        points[stamp] = point
    return tuple(points[stamp] for stamp in sorted(points))


def align_hourly_funding_to_4h(points: tuple[HourlyFundingRate, ...],
                               candle_starts: tuple[datetime, ...]) -> tuple[Decimal, ...]:
    """Sum four signed hourly rates for every 4h candle; reject any missing hour."""
    by_time = {point.timestamp.astimezone(timezone.utc): point.relative_rate for point in points}
    if len(by_time) != len(points):
        raise ValueError("Duplicate hourly funding timestamp")
    aligned = []
    for candle_start in candle_starts:
        if candle_start.tzinfo is None or candle_start.utcoffset() is None:
            raise ValueError("Candle timestamp needs a timezone")
        start = candle_start.astimezone(timezone.utc)
        if start.hour % 4 or start.minute or start.second or start.microsecond:
            raise ValueError("Candle timestamp is not 4h aligned")
        stamps = tuple(start + timedelta(hours=hour) for hour in range(4))
        if any(stamp not in by_time for stamp in stamps):
            raise ValueError(f"Missing hourly funding inside candle {start.isoformat()}")
        aligned.append(sum((by_time[stamp] for stamp in stamps), Decimal("0")))
    return tuple(aligned)
