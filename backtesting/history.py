"""Immutable bounded views avoid copying an ever-growing candle history."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import overload

from app.market_data.models import Candle


@dataclass(frozen=True)
class CandleHistory(Sequence[Candle]):
    _candles: tuple[Candle, ...]
    _length: int

    def __post_init__(self) -> None:
        if not 0 <= self._length <= len(self._candles):
            raise ValueError("Invalid history boundary")

    def __len__(self) -> int:
        return self._length

    @overload
    def __getitem__(self, index: int) -> Candle: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Candle, ...]: ...

    def __getitem__(self, index: int | slice) -> Candle | tuple[Candle, ...]:
        if isinstance(index, slice):
            return tuple(self._candles[i] for i in range(*index.indices(self._length)))
        if index < 0:
            index += self._length
        if not 0 <= index < self._length:
            raise IndexError("Candle outside observed history")
        return self._candles[index]
