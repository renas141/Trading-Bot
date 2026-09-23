"""Pure analysis interface: only already-closed candles are provided."""

from abc import ABC, abstractmethod
from typing import Sequence

from app.market_data.models import Candle
from app.strategies.models import Signal


class Strategy(ABC):
    @abstractmethod
    def analyze(self, history: Sequence[Candle]) -> Signal:
        """Return an explainable signal without accessing a broker or exchange."""
