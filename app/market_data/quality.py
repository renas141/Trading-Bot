"""Deterministic data audit. Missing intervals are reported, never invented."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Sequence

from app.domain import aware_timestamp
from app.market_data.models import Candle, TIMEFRAMES


@dataclass(frozen=True)
class QualityReport:
    rows: int
    expected_rows: int
    missing_intervals: int
    gaps: tuple[dict[str, object], ...]
    errors: tuple[str, ...]
    zero_volume_rows: int
    start: str
    end_exclusive: str

    @property
    def ready(self) -> bool:
        return self.rows > 0 and self.missing_intervals == 0 and not self.errors

    def as_dict(self) -> dict[str, object]:
        return {**asdict(self), "ready": self.ready}


def audit_candles(candles: Sequence[Candle], symbol: str, timeframe: str,
                  start: datetime, end: datetime, *, as_of: datetime | None = None) -> QualityReport:
    """Audit a half-open [start, end) range aligned to UTC timeframe boundaries."""
    for stamp in (start, end):
        aware_timestamp(stamp)
    seconds = TIMEFRAMES[timeframe]
    if start >= end or any(t.microsecond or int(t.timestamp()) % seconds for t in (start, end)):
        raise ValueError("Range must be nonempty and aligned to UTC timeframe boundaries")
    as_of = as_of or datetime.now(timezone.utc)
    aware_timestamp(as_of)
    first, last = int(start.timestamp()), int(end.timestamp())
    errors: set[str] = set()
    valid_stamps: set[int] = set()
    seen: set[datetime] = set()
    previous = None
    for candle in candles:
        if (candle.symbol, candle.timeframe) != (symbol, timeframe):
            errors.add("mixed_symbol_or_timeframe")
        stamp = int(candle.timestamp.timestamp())
        aligned = not candle.timestamp.microsecond and stamp % seconds == 0
        if not aligned:
            errors.add("off_grid_timestamp")
        if candle.timestamp in seen:
            errors.add("duplicate_timestamp")
        seen.add(candle.timestamp)
        if previous is not None and candle.timestamp < previous.closed_at:
            errors.add("unsorted_or_overlapping")
        previous = candle
        if not first <= stamp < last or candle.closed_at > end:
            errors.add("outside_requested_range")
        elif aligned:
            valid_stamps.add(stamp)
        if candle.closed_at > as_of:
            errors.add("unfinished_candle")
    gaps = []
    cursor = first
    for stamp in sorted(valid_stamps) + [last]:
        if stamp > cursor:
            gaps.append({"start": datetime.fromtimestamp(cursor, timezone.utc).isoformat(),
                         "end_exclusive": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                         "missing_intervals": (stamp - cursor) // seconds})
        cursor = stamp + seconds
    expected = (last - first) // seconds
    return QualityReport(len(candles), expected, expected - len(valid_stamps), tuple(gaps),
                         tuple(sorted(errors)), sum(c.volume == 0 for c in candles),
                         start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat())


def require_complete(candles: Sequence[Candle]) -> QualityReport:
    if not candles:
        raise ValueError("Historical data must not be empty")
    report = audit_candles(candles, candles[0].symbol, candles[0].timeframe,
                           min(c.timestamp for c in candles), max(c.closed_at for c in candles))
    if not report.ready:
        raise ValueError(f"Data quality failed: missing={report.missing_intervals}, errors={report.errors}")
    return report
