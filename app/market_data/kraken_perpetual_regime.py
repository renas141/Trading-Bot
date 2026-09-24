"""Public PF_XBTUSD regime analytics with strict schema and time alignment."""

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
KINDS = (
    "open-interest",
    "aggressor-differential",
    "liquidation-volume",
    "rolling-volatility",
    "long-short-ratio",
    "cvd",
)
MAX_RESPONSE_BYTES = 2_000_000
MAX_LOOKBACK_SECONDS = 3600


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str) -> bytes:
    """Allow only bounded public PF_XBTUSD regime analytics requests."""
    parsed = urlsplit(url)
    prefix = "/api/charts/v1/analytics/PF_XBTUSD/"
    kind = parsed.path.removeprefix(prefix) if parsed.path.startswith(prefix) else ""
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
        since = int(query["since"][0])
        end = int(query["to"][0])
        interval = int(query["interval"][0])
    except (KeyError, TypeError, ValueError, IndexError):
        raise MarketDataError("Invalid Kraken regime analytics query") from None
    if (parsed.scheme != "https" or parsed.netloc != "futures.kraken.com" or parsed.fragment
            or kind not in KINDS or set(query) != {"since", "to", "interval"}
            or any(len(values) != 1 for values in query.values())
            or interval != 60 or since < 0 or end <= since
            or end - since > MAX_LOOKBACK_SECONDS):
        raise MarketDataError("Only bounded public PF_XBTUSD regime analytics are allowed")
    try:
        request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Kraken regime response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Kraken regime request failed (HTTP {status})") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Kraken regime analytics endpoint unavailable") from None


def _number(value: object, name: str, *, nonnegative=False, positive=False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"Invalid {name}")
    number = Decimal(str(value))
    if (not number.is_finite() or (nonnegative and number < 0)
            or (positive and number <= 0)):
        raise ValueError(f"Invalid {name}")
    return number


def _payload(raw: bytes, kind: str, start: int, end: int) -> tuple[list[int], object]:
    try:
        payload = json.loads(raw, parse_float=Decimal)
        result = payload["result"]
        timestamps = result["timestamp"]
        data = result["data"]
        if (payload.get("errors") != [] or result.get("more") is not False
                or not isinstance(timestamps, list) or not 1 <= len(timestamps) <= 62):
            raise ValueError("Partial or malformed analytics payload")
        seconds = []
        previous = None
        for stamp in timestamps:
            if type(stamp) is not int or stamp % 60 or not start - 60 <= stamp <= end:
                raise ValueError("Unaligned or out-of-range analytics timestamp")
            if previous is not None and stamp <= previous:
                raise ValueError("Analytics timestamps are not increasing")
            seconds.append(stamp)
            previous = stamp
        return seconds, data
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ArithmeticError):
        raise MarketDataError(f"Malformed Kraken {kind} response") from None


def _simple(data: object, length: int, name: str, *, nonnegative=False) -> list[Decimal]:
    if not isinstance(data, list) or len(data) != length:
        raise MarketDataError(f"Malformed Kraken {name} series")
    try:
        return [_number(value, name, nonnegative=nonnegative) for value in data]
    except (ValueError, ArithmeticError):
        raise MarketDataError(f"Malformed Kraken {name} series") from None


@dataclass(frozen=True)
class RegimeSnapshot:
    symbol: str
    event_at: datetime
    requested_at: datetime
    received_at: datetime
    open_interest: Decimal
    aggressor_differential: Decimal
    liquidation_volume: Decimal
    rolling_volatility: Decimal
    long_short_ratio: Decimal
    buy_volume: Decimal
    sell_volume: Decimal
    cumulative_volume_delta: Decimal
    raw: dict[str, bytes]
    urls: dict[str, str]

    def metrics(self) -> dict[str, Decimal]:
        return {
            "open_interest": self.open_interest,
            "aggressor_differential": self.aggressor_differential,
            "liquidation_volume": self.liquidation_volume,
            "rolling_volatility": self.rolling_volatility,
            "long_short_ratio": self.long_short_ratio,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "cumulative_volume_delta": self.cumulative_volume_delta,
        }


class KrakenPerpetualRegimeAdapter:
    """One recent, common-minute public regime snapshot for PF_XBTUSD."""

    def __init__(self, transport: Callable[[str], bytes] = public_get,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 lookback_seconds: int = 3600) -> None:
        if not 120 <= lookback_seconds <= MAX_LOOKBACK_SECONDS or lookback_seconds % 60:
            raise ValueError("Regime lookback must be 120..3600 seconds and minute-aligned")
        self._transport, self._clock, self._lookback = transport, clock, lookback_seconds

    def snapshot(self) -> RegimeSnapshot:
        requested = self._clock()
        aware_timestamp(requested)
        end = int(requested.timestamp()) // 60 * 60
        start = end - self._lookback
        raw, urls, parsed = {}, {}, {}
        for kind in KINDS:
            url = ROOT + kind + "?" + urlencode({"since": start, "to": end, "interval": 60})
            response = self._transport(url)
            if not isinstance(response, bytes) or len(response) > MAX_RESPONSE_BYTES:
                raise MarketDataError("Invalid or oversized Kraken regime response")
            raw[kind], urls[kind] = response, url
            parsed[kind] = _payload(response, kind, start, end)
        received = self._clock()
        aware_timestamp(received)
        if received < requested:
            raise MarketDataError("Local clock moved backwards during regime request")
        common = set.intersection(*(set(times) for times, _ in parsed.values()))
        if not common:
            raise MarketDataError("Kraken regime analytics have no common timestamp")
        event_seconds = max(common)
        if event_seconds > int(received.timestamp()):
            raise MarketDataError("Kraken regime timestamp is in the future")

        values = {}
        for kind in KINDS:
            times, data = parsed[kind]
            index = times.index(event_seconds)
            if kind == "open-interest":
                if not isinstance(data, list) or len(data) != len(times):
                    raise MarketDataError("Malformed Kraken open-interest series")
                try:
                    rows = []
                    for row in data:
                        if not isinstance(row, list) or len(row) != 4:
                            raise ValueError("Open interest must be OHLC")
                        rows.append([_number(item, kind, positive=True) for item in row])
                    values[kind] = rows[index][3]
                except (ValueError, ArithmeticError):
                    raise MarketDataError("Malformed Kraken open-interest series") from None
            elif kind == "cvd":
                if not isinstance(data, dict) or set(data) != {"buy_volume", "sell_volume", "cvd"}:
                    raise MarketDataError("Malformed Kraken CVD series")
                buy = _simple(data["buy_volume"], len(times), "buy volume", nonnegative=True)
                sell = _simple(data["sell_volume"], len(times), "sell volume", nonnegative=True)
                cvd = _simple(data["cvd"], len(times), "CVD")
                values[kind] = (buy[index], sell[index], cvd[index])
            else:
                values[kind] = _simple(
                    data, len(times), kind,
                    nonnegative=kind in ("liquidation-volume", "rolling-volatility", "long-short-ratio"),
                )[index]

        buy, sell, cvd = values["cvd"]
        return RegimeSnapshot(
            "PF_XBTUSD", datetime.fromtimestamp(event_seconds, timezone.utc), requested, received,
            values["open-interest"], values["aggressor-differential"],
            values["liquidation-volume"], values["rolling-volatility"],
            values["long-short-ratio"], buy, sell, cvd, raw, urls,
        )
