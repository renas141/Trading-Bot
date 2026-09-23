"""Bounded, read-only historical Kraken trades with replayable raw evidence."""

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from app.domain import aware_timestamp, positive_decimal
from app.errors import MarketDataError
from app.exchange.kraken import _NoRedirect
from app.market_data.cli import timestamp
from app.market_data.datasets import sha256, write_json
from app.market_data.models import Candle

ENDPOINT = "https://api.kraken.com/0/public/Trades"
MAX_PAGES = 200
MAX_BYTES = 20_000_000


@dataclass(frozen=True)
class PublicTrade:
    id: int
    timestamp: Decimal
    price: Decimal
    volume: Decimal
    side: str
    order_type: str
    misc: str


def public_get(url: str) -> bytes:
    if not url.startswith(ENDPOINT + "?"):
        raise MarketDataError("Only public Kraken trades are permitted")
    try:
        request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise MarketDataError("Trade response exceeds size limit")
        return raw
    except OSError:
        raise MarketDataError("Public trade request failed; partial evidence is not complete") from None


def parse_page(raw: bytes) -> tuple[tuple[PublicTrade, ...], str]:
    try:
        payload = json.loads(raw, parse_float=Decimal)
        result = payload["result"]
        if payload["error"] != [] or set(result) != {"XXBTZEUR", "last"}:
            raise ValueError("Unexpected market or API error")
        cursor, rows = result["last"], result["XXBTZEUR"]
        if not isinstance(cursor, str) or not cursor.isdigit() or not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
            raise ValueError("Invalid trade page")
        trades = []
        for row in rows:
            if (not isinstance(row, list) or len(row) != 7 or type(row[6]) is not int or row[6] < 0
                    or row[3] not in ("b", "s") or row[4] not in ("l", "m") or not isinstance(row[5], str)):
                raise ValueError("Malformed trade")
            stamp, price, volume = Decimal(row[2]), Decimal(row[0]), Decimal(row[1])
            for value in (stamp, price, volume):
                positive_decimal(value, "public trade value")
            trades.append(PublicTrade(row[6], stamp, price, volume, row[3], row[4], row[5]))
        return tuple(trades), cursor
    except (KeyError, ValueError, TypeError, ArithmeticError):
        raise MarketDataError("Malformed public trade response") from None


def request_url(cursor: str) -> str:
    return ENDPOINT + "?" + urlencode({"pair": "XXBTZEUR", "since": cursor, "count": 1000})


def merge_page(seen: dict[int, PublicTrade], page: tuple[PublicTrade, ...], start: Decimal) -> None:
    for trade in page:
        if trade.id in seen:
            if seen[trade.id] != trade:
                raise MarketDataError("Conflicting duplicate trade ID")
            continue
        if trade.timestamp < start:
            raise MarketDataError("Response precedes requested interval")
        if seen:
            previous = next(reversed(seen.values()))
            if trade.id <= previous.id or trade.timestamp < previous.timestamp:
                raise MarketDataError("Trade history is not chronological")
        seen[trade.id] = trade


def collect(start: datetime, end: datetime, output: Path, transport=public_get, pause=time.sleep) -> dict:
    for stamp in (start, end):
        aware_timestamp(stamp)
    if start >= end or start.microsecond or end.microsecond or (end - start).total_seconds() > 86400 or end > datetime.now(timezone.utc):
        raise ValueError("Request a historical whole-second interval of at most one day")
    output.mkdir(parents=True, exist_ok=False)
    low, high = Decimal(int(start.timestamp())), Decimal(int(end.timestamp()))
    cursor, seen, pages, total = str(int(low) * 10**9 - 1), {}, [], 0
    for index in range(MAX_PAGES):
        url = request_url(cursor)
        raw = transport(url)
        total += len(raw)
        if total > MAX_BYTES:
            raise MarketDataError("Historical trade transfer budget exceeded")
        name = f"page-{index:04}.json"
        (output / name).write_bytes(raw)
        trades, next_cursor = parse_page(raw)
        if int(next_cursor) <= int(cursor):
            raise MarketDataError("Trade pagination cursor did not advance")
        merge_page(seen, trades, low)
        pages.append({"file": name, "sha256": sha256(raw), "url": url, "since": cursor, "next": next_cursor})
        print(f"Trade evidence: page {index + 1}, {len(seen)} unique rows", flush=True)
        # A returned trade at or beyond the end is the required boundary witness.
        if next(reversed(seen.values())).timestamp >= high:
            manifest = {"schema_version": 1, "symbol": "BTC/EUR", "endpoint": ENDPOINT,
                        "start": start.isoformat(), "end": end.isoformat(), "complete": True,
                        "captured_at": datetime.now(timezone.utc).isoformat(), "pages": pages,
                        "bytes": total, "unique_rows_including_end_witness": len(seen),
                        "verification": "Ordered public pages, advancing opaque cursors, identical overlaps deduplicated by trade ID, end-boundary witness. Completeness also requires independent candle controls."}
            write_json(output / "manifest.json", manifest)
            return manifest
        cursor = next_cursor
        pause(1.1)
    raise MarketDataError("Historical trade page budget exceeded; no complete manifest published")


def load_evidence(folder: Path) -> tuple[tuple[PublicTrade, ...], dict]:
    manifest = json.loads((folder / "manifest.json").read_text())
    if (manifest.get("schema_version") != 1 or manifest.get("complete") is not True
            or manifest.get("endpoint") != ENDPOINT or manifest.get("symbol") != "BTC/EUR"
            or not 1 <= len(manifest["pages"]) <= MAX_PAGES):
        raise ValueError("Unsupported or incomplete trade evidence")
    start, end = (Decimal(int(datetime.fromisoformat(manifest[k]).timestamp())) for k in ("start", "end"))
    cursor, seen, total = str(int(start) * 10**9 - 1), {}, 0
    for index, item in enumerate(manifest["pages"]):
        if item["file"] != f"page-{index:04}.json" or item["since"] != cursor or item["url"] != request_url(cursor):
            raise ValueError("Evidence page chain or URL differs")
        raw = (folder / item["file"]).read_bytes()
        total += len(raw)
        if sha256(raw) != item["sha256"] or total > MAX_BYTES:
            raise ValueError("Trade evidence checksum or size mismatch")
        trades, next_cursor = parse_page(raw)
        if item["next"] != next_cursor or int(next_cursor) <= int(cursor):
            raise ValueError("Invalid recorded cursor")
        merge_page(seen, trades, start)
        cursor = next_cursor
    if not seen or next(reversed(seen.values())).timestamp < end or total != manifest["bytes"]:
        raise ValueError("Evidence has no end-boundary witness or wrong size")
    return tuple(t for t in seen.values() if start <= t.timestamp < end), manifest


def aggregate_4h(trades: tuple[PublicTrade, ...], start: datetime, end: datetime) -> tuple[Candle, ...]:
    if any(t.microsecond or int(t.timestamp()) % 14400 for t in (start, end)) or start >= end:
        raise ValueError("Four-hour boundaries required")
    grouped = {}
    for trade in trades:
        bucket = int(trade.timestamp) // 14400 * 14400
        if not int(start.timestamp()) <= bucket < int(end.timestamp()):
            raise ValueError("Trade outside aggregation window")
        grouped.setdefault(bucket, []).append(trade)
    candles = []
    for stamp in range(int(start.timestamp()), int(end.timestamp()), 14400):
        rows = grouped.get(stamp)
        if not rows:
            raise ValueError("Empty trade interval; no candle may be invented")
        prices = [r.price for r in rows]
        candles.append(Candle("BTC/EUR", "4h", datetime.fromtimestamp(stamp, timezone.utc),
                              prices[0], max(prices), min(prices), prices[-1], sum((r.volume for r in rows), Decimal(0))))
    return tuple(candles)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Public BTC/EUR trade evidence for candle reconciliation")
    parser.add_argument("--start", type=timestamp, required=True)
    parser.add_argument("--end", type=timestamp, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    collect(args.start, args.end, args.output)


if __name__ == "__main__":
    main()
