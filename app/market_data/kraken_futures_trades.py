"""Bounded public PF_XBTUSD recent-trade archive with verified pagination."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.errors import MarketDataError


ROOT = "https://futures.kraken.com/derivatives/api/v3/history"
DOCUMENTATION = "https://docs.kraken.com/api/docs/futures-api/trading/get-history"
MAX_RESPONSE_BYTES = 4_000_000
MAX_PAGES = 100
TRADE_TYPES = {"fill", "liquidation", "partial liquidation", "full liquidation"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str) -> bytes:
    parsed = urlsplit(url)
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
    except ValueError:
        raise MarketDataError("Invalid Kraken recent-trades query") from None
    if (parsed.scheme != "https" or parsed.netloc != "futures.kraken.com"
            or parsed.path != "/derivatives/api/v3/history" or parsed.fragment
            or set(query) - {"symbol", "lastTime"}
            or query.get("symbol") != ["PF_XBTUSD"]
            or any(len(values) != 1 for values in query.values())):
        raise MarketDataError("Only public PF_XBTUSD recent trades are allowed")
    if "lastTime" in query:
        try:
            stamp = datetime.fromisoformat(query["lastTime"][0].replace("Z", "+00:00"))
        except ValueError:
            raise MarketDataError("Invalid Kraken trade cursor") from None
        if stamp.tzinfo is None:
            raise MarketDataError("Kraken trade cursor needs a timezone")
    try:
        request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Kraken recent-trades response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Kraken recent-trades request failed (HTTP {status})") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Kraken recent-trades endpoint unavailable") from None


def _decimal(value: object, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid trade {label}") from None
    if not number.is_finite() or number <= 0:
        raise ValueError(f"Invalid trade {label}")
    return number


def parse_page(raw: bytes) -> list[dict]:
    try:
        payload = json.loads(raw)
        rows = payload["history"]
        if payload.get("result") != "success" or not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("Malformed trade page")
        parsed = []
        previous_timestamp = None
        for row in rows:
            timestamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            sequence = int(row["sequence_id"])
            if (timestamp.tzinfo is None or sequence <= 0 or row.get("side") not in {"buy", "sell"}
                    or row.get("type") not in TRADE_TYPES or not isinstance(row.get("uid"), str)
                    or not row["uid"]):
                raise ValueError("Malformed trade row")
            item = {
                "time": row["time"], "timestamp": timestamp.astimezone(timezone.utc),
                "sequence_id": sequence, "uid": row["uid"], "side": row["side"],
                "type": row["type"],
                "price": _decimal(row["price"], "price"),
                "size": _decimal(row["size"], "size"),
            }
            if previous_timestamp is not None and item["timestamp"] < previous_timestamp:
                raise ValueError("Trade page timestamps are not chronological")
            previous_timestamp = item["timestamp"]
            parsed.append(item)
        return parsed
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise MarketDataError("Malformed Kraken recent-trades response") from None


def _cursor(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError("Trade cursor must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Trade cursor needs a timezone")
    return value


def collect(output: Path, pages: int = 25, before: str | None = None,
            transport: Callable[[str], bytes] = public_get,
            clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    captured = clock()
    if output.exists() or not 1 <= pages <= MAX_PAGES or captured.tzinfo is None:
        raise ValueError("Use a new directory and 1..100 pages")
    if before is not None:
        try:
            before_time = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Trade cursor must be an ISO-8601 timestamp") from None
        if before_time.tzinfo is None or before_time > captured:
            raise ValueError("Trade cursor needs a timezone and cannot be in the future")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=output.parent) as directory:
            temporary = Path(directory)
            all_rows: dict[str, dict] = {}
            page_records = []
            cursor = before
            for page in range(pages):
                query = {"symbol": "PF_XBTUSD"}
                if cursor is not None:
                    query["lastTime"] = cursor
                url = ROOT + "?" + urlencode(query)
                raw = transport(url)
                if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
                    raise MarketDataError("Invalid or oversized Kraken recent-trades response")
                rows = parse_page(raw)
                if not rows:
                    break
                oldest = rows[0]["time"]
                if cursor is not None and oldest >= cursor:
                    raise ValueError("Kraken recent-trades pagination did not move backwards")
                raw_name = f"page-{page:03}.json"
                (temporary / raw_name).write_bytes(raw)
                page_records.append({
                    "file": raw_name, "url": url, "rows": len(rows),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "oldest": rows[0]["time"], "newest": rows[-1]["time"],
                })
                for row in rows:
                    prior = all_rows.get(row["uid"])
                    if prior is not None and prior != row:
                        raise ValueError("Conflicting duplicate Kraken trade")
                    all_rows[row["uid"]] = row
                cursor = oldest

            ordered = sorted(all_rows.values(), key=lambda row: (row["timestamp"], row["sequence_id"]))
            if not ordered:
                raise ValueError("No Kraken trades collected")
            with (temporary / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=(
                    "time", "sequence_id", "uid", "side", "type", "price", "size", "notional_usd",
                ))
                writer.writeheader()
                for row in ordered:
                    writer.writerow({
                        "time": row["time"], "sequence_id": row["sequence_id"],
                        "uid": row["uid"], "side": row["side"], "type": row["type"],
                        "price": str(row["price"]),
                        "size": str(row["size"]), "notional_usd": str(row["price"] * row["size"]),
                    })
            total_size = sum((row["size"] for row in ordered), Decimal("0"))
            total_notional = sum((row["price"] * row["size"] for row in ordered), Decimal("0"))
            side_volume = {
                side: sum((row["size"] for row in ordered if row["side"] == side), Decimal("0"))
                for side in ("buy", "sell")
            }
            type_counts = {
                kind: sum(row["type"] == kind for row in ordered)
                for kind in sorted({row["type"] for row in ordered})
            }
            summary = {
                "schema_version": 1, "provider": "Kraken Futures", "market": "PF_XBTUSD",
                "captured_at": captured.astimezone(timezone.utc).isoformat(),
                "requested_before": before,
                "pages": len(page_records), "unique_trades": len(ordered),
                "oldest_trade": ordered[0]["time"], "newest_trade": ordered[-1]["time"],
                "minimum_price": str(min(row["price"] for row in ordered)),
                "maximum_price": str(max(row["price"] for row in ordered)),
                "total_size_btc": str(total_size), "total_notional_usd": str(total_notional),
                "vwap": str(total_notional / total_size),
                "buy_size_btc": str(side_volume["buy"]),
                "sell_size_btc": str(side_volume["sell"]),
                "trade_type_counts": type_counts,
                "raw_integrity_checked": True, "live_enabled": False,
                "limitations": [
                    "The endpoint exposes at most the recent seven days or the latest engine restart.",
                    "Time-based page cursors cannot prove that every trade at a page boundary is available.",
                    "Public trades measure executed flow; they do not prove an obtainable fill.",
                    "No credentials or order endpoint are used.",
                ],
            }
            (temporary / "summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            manifest = {
                "schema_version": 1, "provider": "Kraken Futures", "market": "PF_XBTUSD",
                "documentation": DOCUMENTATION, "requested_before": before,
                "pages": page_records,
                "normalized_sha256": hashlib.sha256((temporary / "trades.csv").read_bytes()).hexdigest(),
            }
            (temporary / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            temporary.replace(output)
        return summary
    except BaseException:
        if output.exists():
            shutil.rmtree(output)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect recent public PF_XBTUSD trades")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pages", type=int, default=25)
    parser.add_argument("--before", type=_cursor)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(collect(args.output, args.pages, args.before), indent=2))
        return 0
    except (OSError, ValueError, MarketDataError) as exc:
        print(f"Recent-trades collection failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
