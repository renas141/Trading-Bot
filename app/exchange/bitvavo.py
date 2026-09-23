"""Bounded public Bitvavo Spot data. No credentials, orders or private endpoints."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.domain import aware_timestamp, positive_decimal
from app.errors import MarketDataError
from app.exchange.base import ExchangeAdapter
from app.market_data.models import Candle, TIMEFRAMES

ROOT = "https://api.bitvavo.com/v2/"
MAX_RESPONSE_BYTES = 2_000_000
MAX_BARS = 1440


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str) -> bytes:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, strict_parsing=True)
    permitted = {
        "/v2/markets": {"market"}, "/v2/ticker/book": {"market"},
        "/v2/BTC-EUR/candles": {"interval", "start", "end", "limit"},
    }
    if (parsed.scheme != "https" or parsed.netloc != "api.bitvavo.com" or parsed.fragment
            or parsed.path not in permitted or set(query) != permitted[parsed.path]
            or any(len(values) != 1 for values in query.values())
            or ("market" in query and query["market"] != ["BTC-EUR"])):
        raise MarketDataError("Only approved public Bitvavo BTC/EUR data endpoints are allowed")
    try:
        request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Bitvavo response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Bitvavo public request failed (HTTP {status}); no retry performed") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Bitvavo public endpoint unavailable") from None


@dataclass(frozen=True)
class PublicDownload:
    raw: bytes
    request_url: str
    requested_at: datetime


@dataclass(frozen=True)
class CandleDownload(PublicDownload):
    candles: tuple[Candle, ...]


@dataclass(frozen=True)
class Instrument(PublicDownload):
    status: str
    tick_size: Decimal
    quantity_step: Decimal
    minimum_quantity: Decimal
    minimum_notional: Decimal
    fee_category: str


@dataclass(frozen=True)
class BookSnapshot(PublicDownload):
    """requested_at is local request time, NOT a venue event timestamp."""
    received_at: datetime
    bid: Decimal
    bid_size: Decimal
    ask: Decimal
    ask_size: Decimal

    @property
    def spread_bps(self) -> Decimal:
        return (self.ask - self.bid) / ((self.ask + self.bid) / 2) * 10000


def _number(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("Expected decimal string")
    result = Decimal(value)
    positive_decimal(result, "market value")
    return result


class BitvavoAdapter(ExchangeAdapter):
    def __init__(self, transport: Callable[[str], bytes] = public_get,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._transport, self._clock = transport, clock

    def _get(self, path: str, query: dict[str, object]) -> PublicDownload:
        now = self._clock()
        aware_timestamp(now)
        url = ROOT + path + "?" + urlencode(query)
        raw = self._transport(url)
        if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Invalid or oversized Bitvavo response")
        return PublicDownload(raw, url, now)

    def fetch_candles(self, symbol: str, timeframe: str, since: datetime) -> tuple[Candle, ...]:
        seconds = TIMEFRAMES.get(timeframe)
        if seconds is None:
            raise MarketDataError("Unsupported timeframe")
        now = self._clock()
        aware_timestamp(now)
        end = datetime.fromtimestamp(int(now.timestamp()) // seconds * seconds, timezone.utc)
        return self.download(symbol, timeframe, since, end).candles

    def download(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> CandleDownload:
        if symbol != "BTC/EUR" or timeframe not in TIMEFRAMES:
            raise MarketDataError("Bitvavo adapter currently supports BTC/EUR and configured timeframes only")
        for stamp in (start, end):
            aware_timestamp(stamp)
        seconds = TIMEFRAMES[timeframe]
        now = self._clock()
        aware_timestamp(now)
        if (start >= end or end > now
                or any(t.microsecond or int(t.timestamp()) % seconds for t in (start, end))
                or (end - start).total_seconds() > MAX_BARS * seconds):
            raise MarketDataError("Request 1..1440 closed intervals aligned to UTC boundaries")
        # Bitvavo returns bars whose CLOSE is <= the aligned end boundary.
        # Verified with a two-bar public request; subtracting 1 ms loses a bar.
        fetched = self._get("BTC-EUR/candles", {
            "interval": timeframe, "start": int(start.timestamp()) * 1000,
            "end": int(end.timestamp()) * 1000, "limit": MAX_BARS,
        })
        try:
            rows = json.loads(fetched.raw)
            if not isinstance(rows, list) or len(rows) > MAX_BARS:
                raise ValueError("Invalid candle array")
            candles = []
            previous = None
            for row in rows:
                if (not isinstance(row, list) or len(row) != 6 or type(row[0]) is not int
                        or row[0] % (seconds * 1000)):
                    raise ValueError("Malformed or unaligned candle")
                stamp = datetime.fromtimestamp(row[0] // 1000, timezone.utc)
                if previous is not None and stamp >= previous:
                    raise ValueError("Candles must be strictly descending without duplicates")
                if not start <= stamp < end:
                    raise ValueError("Candle outside requested range")
                if not all(isinstance(v, str) for v in row[1:]):
                    raise ValueError("Expected decimal strings")
                candle = Candle(symbol, timeframe, stamp, *(Decimal(v) for v in row[1:]))
                if candle.closed_at > fetched.requested_at:
                    raise ValueError("Unfinished candle")
                candles.append(candle)
                previous = stamp
            return CandleDownload(fetched.raw, fetched.request_url, fetched.requested_at,
                                  tuple(reversed(candles)))
        except (ValueError, TypeError, ArithmeticError, OverflowError, OSError):
            raise MarketDataError("Malformed Bitvavo candle response") from None

    def instrument(self) -> Instrument:
        fetched = self._get("markets", {"market": "BTC-EUR"})
        try:
            row = json.loads(fetched.raw)
            if (row["market"] != "BTC-EUR" or row["base"] != "BTC" or row["quote"] != "EUR"
                    or row["status"] not in {"trading", "halted", "auction", "auctionMatching", "cancelOnly"}
                    or type(row["quantityDecimals"]) is not int
                    or not 0 <= row["quantityDecimals"] <= 18
                    or not isinstance(row["feeCategory"], str) or not row["feeCategory"]):
                raise ValueError("Invalid market metadata")
            return Instrument(fetched.raw, fetched.request_url, fetched.requested_at, row["status"],
                              _number(row["tickSize"]), Decimal(1).scaleb(-row["quantityDecimals"]),
                              _number(row["minOrderInBaseAsset"]), _number(row["minOrderInQuoteAsset"]),
                              row["feeCategory"])
        except (ValueError, KeyError, TypeError, ArithmeticError):
            raise MarketDataError("Malformed Bitvavo instrument response") from None

    def book(self) -> BookSnapshot:
        fetched = self._get("ticker/book", {"market": "BTC-EUR"})
        received = self._clock()
        aware_timestamp(received)
        if received < fetched.requested_at:
            raise MarketDataError("Local clock moved backwards during quote request")
        try:
            row = json.loads(fetched.raw)
            if row["market"] != "BTC-EUR":
                raise ValueError("Wrong market")
            bid, bid_size, ask, ask_size = (_number(row[k]) for k in ("bid", "bidSize", "ask", "askSize"))
            if bid >= ask:
                raise ValueError("Locked or crossed book")
            return BookSnapshot(fetched.raw, fetched.request_url, fetched.requested_at,
                                received, bid, bid_size, ask, ask_size)
        except (ValueError, KeyError, TypeError, ArithmeticError):
            raise MarketDataError("Malformed Bitvavo book response") from None
