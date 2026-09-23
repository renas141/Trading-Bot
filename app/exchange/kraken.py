"""Read-only Kraken Spot OHLC adapter. No credentials or private endpoints."""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.domain import aware_timestamp
from app.errors import MarketDataError
from app.exchange.base import ExchangeAdapter
from app.market_data.models import Candle, TIMEFRAMES

ENDPOINT = "https://api.kraken.com/0/public/OHLC"
MAX_RESPONSE_BYTES = 2_000_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str) -> bytes:
    """Bounded public GET, at most three attempts; no redirects or authentication."""
    if not url.startswith(ENDPOINT + "?"):
        raise MarketDataError("Only the public Kraken OHLC endpoint is allowed")
    opener = build_opener(_NoRedirect())
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
            with opener.open(request, timeout=15) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise MarketDataError("OHLC response exceeds size limit")
            return raw
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status not in {429, 500, 502, 503, 504} or attempt == 2:
                raise MarketDataError(f"Kraken public request failed (HTTP {status})") from None
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                raise MarketDataError("Kraken public endpoint unavailable; check network access") from None
        time.sleep(attempt + 1)
    raise MarketDataError("Kraken public endpoint unavailable")


@dataclass(frozen=True)
class CandleDownload:
    candles: tuple[Candle, ...]
    raw: bytes
    request_url: str
    requested_at: datetime


class KrakenAdapter(ExchangeAdapter):
    def __init__(self, transport: Callable[[str], bytes] = public_get,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._transport = transport
        self._clock = clock

    def fetch_candles(self, symbol: str, timeframe: str, since: datetime) -> tuple[Candle, ...]:
        return self.download(symbol, timeframe, since).candles

    def download(self, symbol: str, timeframe: str, since: datetime,
                 end: datetime | None = None) -> CandleDownload:
        if symbol != "BTC/EUR" or timeframe not in TIMEFRAMES:
            raise MarketDataError("Kraken adapter currently supports BTC/EUR and configured timeframes only")
        aware_timestamp(since)
        requested_at = self._clock()
        aware_timestamp(requested_at)
        end = end or requested_at
        aware_timestamp(end)
        if since >= end or end > requested_at:
            raise MarketDataError("Requested range must end after its start and not in the future")
        query = urlencode({"pair": "XBTEUR", "interval": TIMEFRAMES[timeframe] // 60,
                           "since": int(since.timestamp())})
        url = ENDPOINT + "?" + query
        raw = self._transport(url)
        try:
            payload = json.loads(raw, parse_float=Decimal)
            if not isinstance(payload, dict) or payload.get("error") != []:
                raise ValueError("API error or missing error field")
            result = payload["result"]
            if set(result) != {"XXBTZEUR", "last"}:
                raise ValueError("Unexpected market in response")
            rows = result["XXBTZEUR"]
            if not isinstance(rows, list) or not rows or len(rows) > 720:
                raise ValueError("Invalid OHLC array")
            candles = []
            previous = None
            for row in rows:
                if not isinstance(row, list) or len(row) != 8 or type(row[0]) is not int:
                    raise ValueError("Invalid OHLC row")
                candle = Candle(symbol, timeframe, datetime.fromtimestamp(row[0], timezone.utc),
                                *(Decimal(row[i]) for i in (1, 2, 3, 4, 6)))
                if previous is not None and candle.timestamp < previous.closed_at:
                    raise ValueError("Unsorted or overlapping OHLC rows")
                candles.append(candle)
                previous = candle
            # Kraken explicitly includes a final, not-yet-committed candle.
            closed = tuple(c for c in candles[:-1] if since <= c.timestamp and c.closed_at <= end)
            return CandleDownload(closed, raw, url, requested_at)
        except (ValueError, TypeError, KeyError, ArithmeticError, OverflowError, OSError):
            raise MarketDataError("Malformed Kraken OHLC response") from None
