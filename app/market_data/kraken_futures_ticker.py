"""Strict public Kraken Futures ticker adapter; no credentials or orders."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.domain import aware_timestamp
from app.errors import MarketDataError
from app.market_data.kraken_perpetual_analytics import (
    AnalyticsSnapshot,
    KrakenPerpetualAnalyticsAdapter,
)


TICKERS_URL = "https://futures.kraken.com/derivatives/api/v3/tickers"
MAX_RESPONSE_BYTES = 4_000_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str) -> bytes:
    """Allow only Kraken's fixed public Futures ticker endpoint."""
    parsed = urlsplit(url)
    if (url != TICKERS_URL or parsed.scheme != "https"
            or parsed.netloc != "futures.kraken.com" or parsed.query or parsed.fragment):
        raise MarketDataError("Only the fixed public Kraken Futures ticker is allowed")
    try:
        request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Kraken Futures ticker response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Kraken Futures ticker request failed (HTTP {status})") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Kraken Futures ticker endpoint unavailable") from None


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Expected timestamp string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    aware_timestamp(parsed)
    return parsed.astimezone(timezone.utc)


def _number(value: object, *, positive: bool = False, nonnegative: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise ValueError("Expected JSON number")
    if (not value.is_finite() or (positive and value <= 0)
            or (nonnegative and value < 0)):
        raise ValueError("Invalid ticker number")
    return value


@dataclass(frozen=True)
class FuturesTickerSnapshot:
    symbol: str
    server_time: datetime
    last_trade_at: datetime
    requested_at: datetime
    received_at: datetime
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    mark_price: Decimal
    index_price: Decimal
    last_price: Decimal
    funding_relative_rate: Decimal
    raw: bytes
    url: str = TICKERS_URL


class KrakenFuturesTickerAdapter:
    """Current, validated PF_XBTUSD public mark and top-of-book snapshot."""

    def __init__(self, transport: Callable[[str], bytes] = public_get,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._transport, self._clock = transport, clock

    def snapshot(self) -> FuturesTickerSnapshot:
        requested = self._clock()
        aware_timestamp(requested)
        raw = self._transport(TICKERS_URL)
        received = self._clock()
        aware_timestamp(received)
        if received < requested:
            raise MarketDataError("Local clock moved backwards during ticker request")
        if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Invalid or oversized Kraken Futures ticker response")
        try:
            payload = json.loads(raw, parse_float=Decimal, parse_int=Decimal)
            if payload.get("result") != "success" or not isinstance(payload.get("tickers"), list):
                raise ValueError("Ticker request did not succeed")
            matches = [row for row in payload["tickers"]
                       if isinstance(row, dict) and row.get("symbol") == "PF_XBTUSD"]
            if len(matches) != 1:
                raise ValueError("PF_XBTUSD ticker is missing or duplicated")
            row = matches[0]
            if row.get("pair") != "XBT:USD" or row.get("tag") != "perpetual":
                raise ValueError("Unexpected ticker instrument identity")
            if row.get("suspended") is not False or row.get("postOnly") is not False:
                raise ValueError("PF_XBTUSD is not in normal trading mode")
            server_time, last_trade_at = _timestamp(payload["serverTime"]), _timestamp(row["lastTime"])
            bid, ask = _number(row["bid"], positive=True), _number(row["ask"], positive=True)
            bid_size = _number(row["bidSize"], nonnegative=True)
            ask_size = _number(row["askSize"], nonnegative=True)
            mark = _number(row["markPrice"], positive=True)
            index = _number(row["indexPrice"], positive=True)
            last = _number(row["last"], positive=True)
            funding = _number(row["relativeFundingRate"])
            if bid >= ask or last_trade_at > server_time:
                raise ValueError("Ticker book is crossed or timestamps are inconsistent")
            if abs(mark - index) / index > Decimal("0.20"):
                raise ValueError("Ticker mark and index prices are implausibly far apart")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, ArithmeticError):
            raise MarketDataError("Malformed or inconsistent Kraken Futures ticker") from None
        return FuturesTickerSnapshot(
            "PF_XBTUSD", server_time, last_trade_at, requested, received,
            bid, ask, bid_size, ask_size, mark, index, last, funding, raw,
        )


class KrakenRealtimeMarketAdapter:
    """Combine current ticker prices with recent public execution-depth analytics."""

    def __init__(self, analytics: KrakenPerpetualAnalyticsAdapter | None = None,
                 ticker: KrakenFuturesTickerAdapter | None = None) -> None:
        self._analytics = analytics or KrakenPerpetualAnalyticsAdapter()
        self._ticker = ticker or KrakenFuturesTickerAdapter()

    def snapshot(self) -> AnalyticsSnapshot:
        analytics = self._analytics.snapshot()
        ticker = self._ticker.snapshot()
        if analytics.symbol != ticker.symbol:
            raise MarketDataError("Realtime market evidence instruments differ")

        # The depth endpoint reports executable prices for its minute bucket. Preserve
        # its adverse slippage ratios while anchoring them to the current ticker book.
        execution: dict[str, Decimal | None] = {}
        for name, slippage in analytics.slippage_bps.items():
            if slippage is None:
                execution[name] = None
            elif name.startswith("sell_"):
                execution[name] = ticker.bid * (Decimal("1") - slippage / Decimal("10000"))
            else:
                execution[name] = ticker.ask * (Decimal("1") + slippage / Decimal("10000"))

        return replace(
            analytics,
            event_at=ticker.server_time,
            requested_at=min(analytics.requested_at, ticker.requested_at),
            received_at=max(analytics.received_at, ticker.received_at),
            bid=ticker.bid,
            ask=ticker.ask,
            funding_relative_rate=ticker.funding_relative_rate,
            execution_prices=execution,
            raw={**analytics.raw, "ticker": ticker.raw},
            urls={**analytics.urls, "ticker": ticker.url},
            mark_price=ticker.mark_price,
            mark_event_at=ticker.server_time,
            index_price=ticker.index_price,
            last_trade_at=ticker.last_trade_at,
            bid_size=ticker.bid_size,
            ask_size=ticker.ask_size,
            analytics_event_at=analytics.event_at,
        )
