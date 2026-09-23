"""Public market data interface, deliberately without a send-order method."""

from abc import ABC, abstractmethod
from datetime import datetime

from app.market_data.models import Candle


class ExchangeAdapter(ABC):
    @abstractmethod
    def fetch_candles(self, symbol: str, timeframe: str, since: datetime) -> tuple[Candle, ...]:
        """Fetch available closed candles; callers must audit requested coverage."""
