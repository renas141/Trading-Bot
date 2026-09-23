"""Interface only; no market classification heuristic is invented here."""

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Sequence

from app.market_data.models import Candle


class MarketRegime(StrEnum):
    UNKNOWN = "UNKNOWN"
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    BREAKOUT = "BREAKOUT"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class RegimeDetector(ABC):
    @abstractmethod
    def detect(self, history: Sequence[Candle]) -> MarketRegime:
        """Classify only already-observed market data."""
