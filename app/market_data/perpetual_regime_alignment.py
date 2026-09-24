"""Leakage-resistant alignment of 4h perpetual candles and regime analytics."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Mapping, Sequence

from app.market_data.kraken_perpetual_regime_history import FIELDS, INTERVAL
from app.market_data.models import Candle


SAFETY_LAG_INTERVALS = 1
_STEP = timedelta(seconds=INTERVAL)


@dataclass(frozen=True)
class AlignedRegimeBar:
    """A trade/mark candle paired with an already completed analytics bucket."""

    trade: Candle
    mark: Candle
    regime_timestamp: datetime
    regime: Mapping[str, Decimal]

    @property
    def decision_at(self) -> datetime:
        return self.trade.closed_at

    @property
    def regime_completed_at(self) -> datetime:
        return self.regime_timestamp + _STEP


def align_futures_regime(
    trade: Sequence[Candle],
    mark: Sequence[Candle],
    regime_rows: Sequence[Mapping[str, object]],
) -> tuple[AlignedRegimeBar, ...]:
    """Return the continuous overlap using a full completed-bucket safety lag.

    A regime bucket stamped ``t`` is treated as covering the interval ending at
    ``t + 4h``. It is paired only with the next candle, which closes at
    ``t + 8h``. This deliberately gives the public API a complete extra candle
    before the value can affect a signal.
    """
    if not trade or not mark or not regime_rows:
        raise ValueError("Price and regime histories must be nonempty")
    if len(trade) != len(mark):
        raise ValueError("Trade and mark histories differ in length")
    price_timestamps = tuple(c.timestamp for c in trade)
    if price_timestamps != tuple(c.timestamp for c in mark):
        raise ValueError("Trade and mark histories are not aligned")
    if len(set(price_timestamps)) != len(price_timestamps):
        raise ValueError("Price history contains duplicate timestamps")
    for index, (trade_candle, mark_candle) in enumerate(zip(trade, mark)):
        if (trade_candle.symbol != "BTC/USD" or mark_candle.symbol != "BTC/USD"
                or trade_candle.timeframe != "4h" or mark_candle.timeframe != "4h"
                or (index and trade_candle.timestamp != trade[index - 1].timestamp + _STEP)):
            raise ValueError("Price history must be continuous 4h BTC/USD data")

    by_timestamp: dict[datetime, Mapping[str, object]] = {}
    previous = None
    for row in regime_rows:
        timestamp = row.get("timestamp")
        if (not isinstance(timestamp, datetime) or timestamp.tzinfo is None
                or timestamp.utcoffset() != timedelta(0) or timestamp.microsecond
                or int(timestamp.timestamp()) % INTERVAL
                or (previous is not None and timestamp != previous + _STEP)):
            raise ValueError("Regime history must have a continuous UTC 4h time axis")
        if set(row) != {"timestamp", *FIELDS}:
            raise ValueError("Regime row fields differ from the verified schema")
        if timestamp in by_timestamp:
            raise ValueError("Regime history contains duplicate timestamps")
        by_timestamp[timestamp] = row
        previous = timestamp

    aligned = []
    for trade_candle, mark_candle in zip(trade, mark):
        source_timestamp = trade_candle.timestamp - _STEP * SAFETY_LAG_INTERVALS
        row = by_timestamp.get(source_timestamp)
        if row is None:
            continue
        values = {name: row[name] for name in FIELDS}
        if any(not isinstance(value, Decimal) for value in values.values()):
            raise ValueError("Regime values must be verified decimals")
        bar = AlignedRegimeBar(trade_candle, mark_candle, source_timestamp, values)
        if bar.regime_completed_at > trade_candle.timestamp:
            raise ValueError("Regime data would not be complete before the paired candle")
        aligned.append(bar)

    if not aligned:
        raise ValueError("Price and regime histories do not overlap after the safety lag")
    for previous_bar, current_bar in zip(aligned, aligned[1:]):
        if current_bar.trade.timestamp != previous_bar.trade.timestamp + _STEP:
            raise ValueError("Aligned price/regime overlap is not continuous")
    return tuple(aligned)
