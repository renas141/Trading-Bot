"""Verified local hourly PF_XBTUSD funding bundles for forward research."""

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.errors import MarketDataError
from app.market_data.datasets import write_json
from app.market_data.kraken_funding import (
    DOCUMENTATION,
    HourlyFundingRate,
    parse_hourly_funding,
)


ROOT = "https://futures.kraken.com/api/charts/v1/analytics/PF_XBTUSD/funding"
INTERVAL = 3600
MAX_RANGE_SECONDS = 7 * 24 * INTERVAL
MAX_RESPONSE_BYTES = 4_000_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str) -> bytes:
    parsed = urlsplit(url)
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
        since, end, interval = (int(query[name][0]) for name in ("since", "to", "interval"))
    except (KeyError, TypeError, ValueError, IndexError):
        raise MarketDataError("Invalid Kraken funding-archive query") from None
    if (parsed.scheme != "https" or parsed.netloc != "futures.kraken.com"
            or parsed.path != "/api/charts/v1/analytics/PF_XBTUSD/funding"
            or parsed.fragment or set(query) != {"since", "to", "interval"}
            or any(len(values) != 1 for values in query.values())
            or interval != INTERVAL or since < 0 or end <= since
            or end - since > MAX_RANGE_SECONDS):
        raise MarketDataError("Only bounded public PF_XBTUSD hourly funding is allowed")
    try:
        request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Kraken funding response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Kraken funding request failed (HTTP {status})") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Kraken funding endpoint unavailable") from None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(output: Path, start: datetime, end: datetime,
             transport: Callable[[str], bytes] = public_get,
             clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    captured = clock()
    if (output.exists() or start >= end or start.microsecond or end.microsecond
            or int(start.timestamp()) % INTERVAL or int(end.timestamp()) % INTERVAL
            or (end - start).total_seconds() > MAX_RANGE_SECONDS
            or captured.tzinfo is None or end > captured.astimezone(timezone.utc)):
        raise ValueError("Use a new directory and a completed hourly range of at most seven days")
    url = ROOT + "?" + urlencode({
        "since": int(start.timestamp()), "to": int(end.timestamp()), "interval": INTERVAL,
    })
    raw = transport(url)
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
        raise MarketDataError("Invalid or oversized Kraken funding response")
    points = parse_hourly_funding(raw, start, end)
    expected = tuple(start + timedelta(hours=offset)
                     for offset in range(int((end - start).total_seconds() // INTERVAL)))
    if tuple(point.timestamp for point in points) != expected:
        raise ValueError("Funding archive has missing, duplicate or unexpected hours")

    output.mkdir(parents=True)
    try:
        raw_path = output / "source.raw"
        raw_path.write_bytes(raw)
        csv_path = output / "funding.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(("timestamp", "relative_rate"))
            writer.writerows((point.timestamp.isoformat(), str(point.relative_rate))
                             for point in points)
        quality = {"ready": True, "rows": len(points), "start": start.isoformat(),
                   "end": end.isoformat(), "missing_hours": []}
        write_json(output / "quality.json", quality)
        hashes = {name: _sha(output / name)
                  for name in ("source.raw", "funding.csv", "quality.json")}
        write_json(output / "manifest.json", {
            "schema_version": 1, "market_type": "linear_perpetual_funding",
            "market_id": "PF_XBTUSD", "symbol": "BTC/USD", "timeframe": "1h",
            "timestamp_semantics": "funding analytics interval timestamp",
            "end_semantics": "exclusive", "start": start.isoformat(), "end": end.isoformat(),
            "captured_at": captured.astimezone(timezone.utc).isoformat(),
            "source": {"provider": "Kraken Futures", "documentation": DOCUMENTATION,
                       "url": url, "field": "relativeRate close"},
            "sha256": hashes, "ready": True,
            "activation": {"strategy_selected": False, "paper_enabled": False,
                           "live_enabled": False},
        })
        return quality
    except BaseException:
        shutil.rmtree(output)
        raise


def load_dataset(path: Path) -> tuple[tuple[HourlyFundingRate, ...], dict]:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != 1
            or manifest.get("market_type") != "linear_perpetual_funding"
            or manifest.get("market_id") != "PF_XBTUSD" or manifest.get("timeframe") != "1h"
            or manifest.get("ready") is not True):
        raise ValueError("Funding dataset is not ready")
    hashes = manifest.get("sha256")
    if not isinstance(hashes, dict) or set(hashes) != {"source.raw", "funding.csv", "quality.json"}:
        raise ValueError("Funding dataset must hash every expected file")
    for name, expected_hash in hashes.items():
        if _sha(path / name) != expected_hash:
            raise ValueError(f"Funding dataset checksum mismatch: {name}")
    points = []
    with (path / "funding.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["timestamp", "relative_rate"]:
            raise ValueError("Funding CSV header differs")
        for row in reader:
            timestamp = datetime.fromisoformat(row["timestamp"])
            rate = Decimal(row["relative_rate"])
            points.append(HourlyFundingRate(timestamp, rate))
    start, end = datetime.fromisoformat(manifest["start"]), datetime.fromisoformat(manifest["end"])
    expected = tuple(start + timedelta(hours=offset)
                     for offset in range(int((end - start).total_seconds() // INTERVAL)))
    if tuple(point.timestamp for point in points) != expected:
        raise ValueError("Funding CSV coverage differs from manifest")
    return tuple(points), manifest


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp needs an offset")
    return parsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Download verified PF_XBTUSD hourly funding")
    parser.add_argument("--start", type=_timestamp, required=True)
    parser.add_argument("--end", type=_timestamp, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(download(args.output, args.start, args.end), indent=2))
        return 0
    except (OSError, ValueError, MarketDataError) as exc:
        print(f"Funding-archive download failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
