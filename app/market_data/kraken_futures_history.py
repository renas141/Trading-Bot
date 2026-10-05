"""Bounded public PF_XBTUSD trade/mark history with verified pagination."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.errors import MarketDataError
from app.market_data.kraken_futures import build_dataset, parse_payload


ROOT = "https://futures.kraken.com/api/charts/v1/"
INTERVAL = timedelta(hours=4)
INTERVAL_SECONDS = int(INTERVAL.total_seconds())
MAX_RANGE_SECONDS = 370 * 24 * 60 * 60
MAX_RESPONSE_BYTES = 8_000_000
MAX_PAGES = 100


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str) -> bytes:
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
        start, end = int(query["from"][0]), int(query["to"][0])
    except (KeyError, TypeError, ValueError, IndexError):
        raise MarketDataError("Invalid Kraken futures-history query") from None
    if (parsed.scheme != "https" or parsed.netloc != "futures.kraken.com"
            or parsed.fragment or len(parts) != 6 or parts[:3] != ["api", "charts", "v1"]
            or parts[3] not in {"trade", "mark"}
            or parts[4:] != ["PF_XBTUSD", "4h"]
            or set(query) != {"from", "to"} or any(len(values) != 1 for values in query.values())
            or start < 0 or end <= start or end - start > MAX_RANGE_SECONDS
            or start % INTERVAL_SECONDS or end % INTERVAL_SECONDS):
        raise MarketDataError("Only bounded aligned public PF_XBTUSD history is allowed")
    try:
        request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Kraken futures-history response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Kraken futures-history request failed (HTTP {status})") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Kraken futures-history endpoint unavailable") from None


def download(output: Path, start: datetime, end: datetime,
             transport: Callable[[str], bytes] = public_get,
             clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    captured = clock()
    if (output.exists() or start >= end or start.microsecond or end.microsecond
            or int(start.timestamp()) % INTERVAL_SECONDS
            or int(end.timestamp()) % INTERVAL_SECONDS
            or (end - start).total_seconds() > MAX_RANGE_SECONDS
            or captured.tzinfo is None or end > captured.astimezone(timezone.utc)):
        raise ValueError("Use a new directory and a completed aligned range of at most 370 days")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=output.parent) as directory:
            temporary = Path(directory)
            files: dict[str, list[Path]] = {"trade": [], "mark": []}
            pages: dict[str, list[dict]] = {"trade": [], "mark": []}
            for kind in ("trade", "mark"):
                cursor = start
                for page in range(MAX_PAGES):
                    url = ROOT + f"{kind}/PF_XBTUSD/4h?" + urlencode({
                        "from": int(cursor.timestamp()), "to": int(end.timestamp()),
                    })
                    raw = transport(url)
                    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
                        raise MarketDataError("Invalid or oversized futures-history response")
                    target = temporary / f"{kind}-{page:03}.json"
                    target.write_bytes(raw)
                    candles = parse_payload(raw, kind, cursor, end, allow_more=True)
                    payload = json.loads(raw)
                    more = payload.get("more_candles")
                    if type(more) is not bool or not candles:
                        raise ValueError(f"Kraken {kind} pagination cannot make progress")
                    files[kind].append(target)
                    pages[kind].append({"url": url, "rows": len(candles)})
                    cursor = candles[-1].closed_at
                    if not more:
                        break
                    if cursor >= end:
                        raise ValueError(f"Kraken {kind} pagination flag is inconsistent")
                else:
                    raise ValueError(f"Kraken {kind} history exceeded page limit")
            quality = build_dataset(output, files["trade"], files["mark"], start, end)
        if quality["ready"] is not True:
            raise ValueError("Kraken futures history failed quality checks")
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["captured_at"] = captured.astimezone(timezone.utc).isoformat()
        manifest["source"]["pages"] = pages
        manifest["source"]["purpose"] = "seen development data; not prospective evidence"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        return quality
    except BaseException:
        if output.exists():
            shutil.rmtree(output)
        raise


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp needs an offset")
    return parsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Download verified PF_XBTUSD 4h history")
    parser.add_argument("--start", type=_timestamp, required=True)
    parser.add_argument("--end", type=_timestamp, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(download(args.output, args.start, args.end), indent=2))
        return 0
    except (OSError, ValueError, MarketDataError) as exc:
        print(f"Futures-history download failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
