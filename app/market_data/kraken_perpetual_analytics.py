"""Bounded public Kraken Perpetual analytics; no credentials or orders."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.domain import aware_timestamp
from app.errors import MarketDataError


ROOT = "https://futures.kraken.com/api/charts/v1/analytics/PF_XBTUSD/"
DOCUMENTATION = "https://docs.kraken.com/api/docs/futures-api/charts/market-analytics"
KINDS = ("spreads", "slippage", "funding")
NOTIONALS = ("1k", "10k", "100k", "1m")
MAX_RESPONSE_BYTES = 2_000_000
MAX_LOOKBACK_SECONDS = 3600


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str) -> bytes:
    """Allow only the fixed public PF_XBTUSD analytics endpoints."""
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, strict_parsing=True)
    prefix = "/api/charts/v1/analytics/PF_XBTUSD/"
    kind = parsed.path.removeprefix(prefix) if parsed.path.startswith(prefix) else ""
    try:
        since = int(query["since"][0])
        end = int(query["to"][0])
        interval = int(query["interval"][0])
    except (KeyError, TypeError, ValueError, IndexError):
        raise MarketDataError("Invalid Kraken analytics query") from None
    if (parsed.scheme != "https" or parsed.netloc != "futures.kraken.com" or parsed.fragment
            or kind not in KINDS or set(query) != {"since", "to", "interval"}
            or any(len(values) != 1 for values in query.values())
            or interval != 60 or since < 0 or end <= since
            or end - since > MAX_LOOKBACK_SECONDS):
        raise MarketDataError("Only bounded public PF_XBTUSD analytics are allowed")
    try:
        request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Kraken analytics response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Kraken analytics request failed (HTTP {status})") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Kraken analytics endpoint unavailable") from None


@dataclass(frozen=True)
class AnalyticsSnapshot:
    symbol: str
    event_at: datetime
    requested_at: datetime
    received_at: datetime
    bid: Decimal
    ask: Decimal
    funding_relative_rate: Decimal
    execution_prices: dict[str, Decimal | None]
    raw: dict[str, bytes]
    urls: dict[str, str]

    @property
    def spread_bps(self) -> Decimal:
        return (self.ask - self.bid) / ((self.ask + self.bid) / 2) * Decimal("10000")

    @property
    def slippage_bps(self) -> dict[str, Decimal | None]:
        values: dict[str, Decimal | None] = {}
        for notional in NOTIONALS:
            sell = self.execution_prices[f"sell_{notional}"]
            buy = self.execution_prices[f"buy_{notional}"]
            values[f"sell_{notional}"] = ((self.bid - sell) / self.bid * Decimal("10000")
                                                   if sell is not None else None)
            values[f"buy_{notional}"] = ((buy - self.ask) / self.ask * Decimal("10000")
                                                 if buy is not None else None)
        return values


def _decimal(value: object, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("Expected decimal string")
    number = Decimal(value)
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError("Invalid decimal value")
    return number


def _payload(raw: bytes, kind: str, start: int, end: int) -> tuple[list[int], dict]:
    try:
        payload = json.loads(raw)
        result = payload["result"]
        timestamps = result["timestamp"]
        data = result["data"]
        if (payload.get("errors") != [] or result.get("more") is not False
                or not isinstance(timestamps, list) or not 1 <= len(timestamps) <= 61
                or not isinstance(data, dict)):
            raise ValueError("Partial or malformed analytics payload")
        divisor = 1000 if kind == "funding" else 1
        seconds = []
        previous = None
        for stamp in timestamps:
            if type(stamp) is not int or stamp % (60 * divisor):
                raise ValueError("Unaligned analytics timestamp")
            current = stamp // divisor
            if not start <= current <= end or (previous is not None and current <= previous):
                raise ValueError("Analytics timestamps outside range or not increasing")
            seconds.append(current)
            previous = current
        return seconds, data
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ArithmeticError):
        raise MarketDataError(f"Malformed Kraken {kind} response") from None


def _series(section: dict, key: str, length: int, *, optional: bool = False) -> list[Decimal | None]:
    try:
        raw_values = section[key]
        if not isinstance(raw_values, list) or len(raw_values) != length:
            raise ValueError("Mismatched analytics series")
        values = []
        for value in raw_values:
            if value is None and optional:
                values.append(None)
            else:
                values.append(_decimal(value, positive=True))
        return values
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise MarketDataError("Malformed Kraken analytics series") from None


class KrakenPerpetualAnalyticsAdapter:
    """One coherent, recent public market-cost snapshot for PF_XBTUSD."""

    def __init__(self, transport: Callable[[str], bytes] = public_get,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 lookback_seconds: int = 600) -> None:
        if not 120 <= lookback_seconds <= MAX_LOOKBACK_SECONDS or lookback_seconds % 60:
            raise ValueError("Analytics lookback must be 120..3600 seconds and minute-aligned")
        self._transport, self._clock, self._lookback = transport, clock, lookback_seconds

    def snapshot(self) -> AnalyticsSnapshot:
        requested = self._clock()
        aware_timestamp(requested)
        end = int(requested.timestamp()) // 60 * 60
        start = end - self._lookback
        raw: dict[str, bytes] = {}
        urls: dict[str, str] = {}
        parsed: dict[str, tuple[list[int], dict]] = {}
        for kind in KINDS:
            url = ROOT + kind + "?" + urlencode({"since": start, "to": end, "interval": 60})
            response = self._transport(url)
            if not isinstance(response, bytes) or len(response) > MAX_RESPONSE_BYTES:
                raise MarketDataError("Invalid or oversized Kraken analytics response")
            raw[kind], urls[kind] = response, url
            parsed[kind] = _payload(response, kind, start, end)
        received = self._clock()
        aware_timestamp(received)
        if received < requested:
            raise MarketDataError("Local clock moved backwards during analytics request")

        spread_times, spread_data = parsed["spreads"]
        slippage_times, slippage_data = parsed["slippage"]
        funding_times, funding_data = parsed["funding"]
        common = set(spread_times) & set(slippage_times) & set(funding_times)
        if not common:
            raise MarketDataError("Kraken analytics have no common timestamp")
        event_seconds = max(common)
        if event_seconds > int(received.timestamp()):
            raise MarketDataError("Kraken analytics timestamp is in the future")
        indices = (spread_times.index(event_seconds), slippage_times.index(event_seconds),
                   funding_times.index(event_seconds))

        try:
            bid_values = _series(spread_data["bid"], "best_price", len(spread_times))
            ask_values = _series(spread_data["ask"], "best_price", len(spread_times))
            bid, ask = bid_values[indices[0]], ask_values[indices[0]]
            if bid is None or ask is None or bid >= ask:
                raise ValueError("Locked or crossed analytics book")

            execution: dict[str, Decimal | None] = {}
            for side, label in (("bid", "sell"), ("ask", "buy")):
                section = slippage_data[side]
                for notional in NOTIONALS:
                    values = _series(section, f"slippage_{notional}", len(slippage_times), optional=True)
                    execution[f"{label}_{notional}"] = values[indices[1]]
            for notional in NOTIONALS:
                sell, buy = execution[f"sell_{notional}"], execution[f"buy_{notional}"]
                if (sell is not None and sell > bid) or (buy is not None and buy < ask):
                    raise ValueError("Favourable price mislabeled as adverse slippage")

            relative_rows = funding_data["relativeRate"]
            rate_rows = funding_data["rate"]
            if (not isinstance(relative_rows, list) or len(relative_rows) != len(funding_times)
                    or not isinstance(rate_rows, list) or len(rate_rows) != len(funding_times)):
                raise ValueError("Mismatched funding series")
            for rows in (relative_rows, rate_rows):
                for row in rows:
                    if not isinstance(row, list) or len(row) != 4:
                        raise ValueError("Funding rows must be OHLC arrays")
                    for value in row:
                        _decimal(value)
            funding = _decimal(relative_rows[indices[2]][3])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise MarketDataError("Malformed or inconsistent Kraken analytics snapshot") from None

        return AnalyticsSnapshot(
            "PF_XBTUSD", datetime.fromtimestamp(event_seconds, timezone.utc), requested, received,
            bid, ask, funding, execution, raw, urls,
        )
