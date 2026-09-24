"""Immutable 4h PF_XBTUSD forward evidence bundles; public reads only."""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from app.errors import MarketDataError
from app.market_data.datasets import write_json
from app.market_data.kraken_funding_archive import (
    download as download_funding,
    load_dataset as load_funding_dataset,
)
from app.market_data.kraken_futures import (
    build_dataset as build_price_dataset,
    load_futures_dataset,
    parse_payload as parse_price_payload,
)
from app.market_data.kraken_perpetual_analytics import KrakenPerpetualAnalyticsAdapter
from app.market_data.kraken_perpetual_regime_history import (
    download as download_regime,
    load_dataset as load_regime_dataset,
)


PRICE_ROOT = "https://futures.kraken.com/api/charts/v1/"
PRICE_DOCUMENTATION = "https://docs.kraken.com/api/docs/futures-api/charts/candles"
STEP = timedelta(hours=4)
STEP_SECONDS = int(STEP.total_seconds())
MAX_PRICE_RESPONSE_BYTES = 2_000_000
DEFAULT_ANCHOR = datetime(2026, 9, 24, 8, tzinfo=timezone.utc)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_get_price(url: str) -> bytes:
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
        start, end = int(query["from"][0]), int(query["to"][0])
    except (KeyError, TypeError, ValueError, IndexError):
        raise MarketDataError("Invalid Kraken forward-price query") from None
    if (parsed.scheme != "https" or parsed.netloc != "futures.kraken.com" or parsed.fragment
            or len(parts) != 6 or parts[:3] != ["api", "charts", "v1"]
            or parts[3] not in ("trade", "mark")
            or parts[4:] != ["PF_XBTUSD", "4h"]
            or set(query) != {"from", "to"} or any(len(v) != 1 for v in query.values())
            or start < 0 or end - start != STEP_SECONDS):
        raise MarketDataError("Only one completed public PF_XBTUSD 4h candle is allowed")
    try:
        request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(MAX_PRICE_RESPONSE_BYTES + 1)
        if len(raw) > MAX_PRICE_RESPONSE_BYTES:
            raise MarketDataError("Kraken forward-price response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Kraken forward-price request failed (HTTP {status})") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Kraken forward-price endpoint unavailable") from None


def _range(start: datetime, end: datetime, now: datetime) -> tuple[datetime, datetime]:
    start, end, now = (value.astimezone(timezone.utc) for value in (start, end, now))
    if (end - start != STEP or start.microsecond or end.microsecond
            or int(start.timestamp()) % STEP_SECONDS or end > now):
        raise ValueError("Forward bundle requires one completed UTC-aligned 4h interval")
    return start, end


def download_prices(target: Path, start: datetime, end: datetime,
                    transport: Callable[[str], bytes] = public_get_price) -> None:
    if target.exists():
        raise ValueError("Use a new price target")
    urls, raw = {}, {}
    for kind in ("trade", "mark"):
        url = PRICE_ROOT + f"{kind}/PF_XBTUSD/4h?" + urlencode(
            {"from": int(start.timestamp()), "to": int(end.timestamp())}
        )
        response = transport(url)
        if not isinstance(response, bytes) or len(response) > MAX_PRICE_RESPONSE_BYTES:
            raise MarketDataError("Invalid or oversized Kraken forward-price response")
        candles = parse_price_payload(response, kind, start, end)
        if len(candles) != 1 or candles[0].timestamp != start or candles[0].closed_at != end:
            raise ValueError(f"Kraken {kind} response does not contain exactly the closed interval")
        urls[kind], raw[kind] = url, response
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=target.parent) as directory:
            sources = {}
            for kind in ("trade", "mark"):
                source = Path(directory) / f"{kind}.json"
                source.write_bytes(raw[kind])
                sources[kind] = source
            quality = build_price_dataset(target, [sources["trade"]], [sources["mark"]], start, end)
        if quality["ready"] is not True:
            raise ValueError("Forward price dataset failed quality checks")
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source"]["urls"] = urls
        manifest["activation"] = {"strategy_selected": False, "paper_enabled": False,
                                  "live_enabled": False}
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    except BaseException:
        if target.exists():
            shutil.rmtree(target)
        raise


def write_cost_snapshot(target: Path, adapter) -> None:
    snapshot = adapter.snapshot()
    target.mkdir()
    raw_dir = target / "raw"
    raw_dir.mkdir()
    for kind, raw in snapshot.raw.items():
        (raw_dir / f"{kind}.json").write_bytes(raw)
    write_json(target / "summary.json", {
        "schema_version": 1, "market": snapshot.symbol,
        "event_at": snapshot.event_at.isoformat(),
        "requested_at": snapshot.requested_at.isoformat(),
        "received_at": snapshot.received_at.isoformat(),
        "bid": str(snapshot.bid), "ask": str(snapshot.ask),
        "spread_bps": str(snapshot.spread_bps),
        "funding_relative_rate": str(snapshot.funding_relative_rate),
        "execution_prices": {key: str(value) if value is not None else None
                             for key, value in snapshot.execution_prices.items()},
        "slippage_bps": {key: str(value) if value is not None else None
                         for key, value in snapshot.slippage_bps.items()},
        "urls": snapshot.urls,
        "limitations": [
            "This is a current public analytics snapshot, not a guaranteed fill.",
            "When an older interval is backfilled, the cost snapshot reflects collection time.",
        ],
    })


def bundle_name(start: datetime, end: datetime) -> str:
    return f"pf_xbtusd_{start:%Y%m%dT%H%MZ}_{end:%Y%m%dT%H%MZ}"


def collect_interval(root: Path, start: datetime, end: datetime, *,
                     price_transport=public_get_price, regime_transport=None,
                     funding_transport=None, cost_adapter=None,
                     clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Path:
    now = clock()
    start, end = _range(start, end, now)
    root.mkdir(parents=True, exist_ok=True)
    final = root / bundle_name(start, end)
    if final.exists():
        load_bundle(final)
        return final
    partial = root / f".partial-{uuid4().hex}"
    partial.mkdir()
    try:
        download_prices(partial / "prices", start, end, price_transport)
        regime_kwargs = {"transport": regime_transport} if regime_transport is not None else {}
        funding_kwargs = {"transport": funding_transport} if funding_transport is not None else {}
        download_regime(partial / "regime", start, end, clock=lambda: now, **regime_kwargs)
        download_funding(partial / "funding", start, end, clock=lambda: now, **funding_kwargs)
        write_cost_snapshot(partial / "cost", cost_adapter or KrakenPerpetualAnalyticsAdapter())
        files = sorted(path.relative_to(partial).as_posix()
                       for path in partial.rglob("*") if path.is_file())
        write_json(partial / "bundle.json", {
            "schema_version": 1, "market": "PF_XBTUSD", "timeframe": "4h",
            "start": start.isoformat(), "end": end.isoformat(),
            "collected_at": now.astimezone(timezone.utc).isoformat(),
            "components": ["trade_mark_prices", "regime", "hourly_funding", "cost_snapshot"],
            "sha256": {name: _sha(partial / name) for name in files},
            "ready": True,
            "activation": {"strategy_selected": False, "paper_enabled": False,
                           "live_enabled": False},
        })
        partial.rename(final)
        load_bundle(final)
        return final
    except BaseException:
        if partial.exists():
            shutil.rmtree(partial)
        raise


def load_bundle(path: Path) -> dict:
    manifest = json.loads((path / "bundle.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != 1 or manifest.get("market") != "PF_XBTUSD"
            or manifest.get("timeframe") != "4h" or manifest.get("ready") is not True):
        raise ValueError("Forward bundle is not ready")
    hashes = manifest.get("sha256")
    actual = {item.relative_to(path).as_posix() for item in path.rglob("*")
              if item.is_file() and item.name != "bundle.json"}
    if not isinstance(hashes, dict) or set(hashes) != actual:
        raise ValueError("Forward bundle file inventory differs")
    for name, expected in hashes.items():
        candidate = (path / name).resolve()
        if not candidate.is_relative_to(path.resolve()) or _sha(candidate) != expected:
            raise ValueError(f"Forward bundle checksum mismatch: {name}")
    trade, mark, _ = load_futures_dataset(path / "prices")
    regime, _ = load_regime_dataset(path / "regime")
    funding, _ = load_funding_dataset(path / "funding")
    start, end = datetime.fromisoformat(manifest["start"]), datetime.fromisoformat(manifest["end"])
    if (len(trade) != 1 or len(mark) != 1 or trade[0].timestamp != start
            or trade[0].closed_at != end or len(regime) != 1
            or regime[0]["timestamp"] != start or len(funding) != 4
            or funding[0].timestamp != start or funding[-1].timestamp != end - timedelta(hours=1)):
        raise ValueError("Forward bundle component coverage differs")
    summary = json.loads((path / "cost" / "summary.json").read_text(encoding="utf-8"))
    if summary.get("schema_version") != 1 or summary.get("market") != "PF_XBTUSD":
        raise ValueError("Forward cost snapshot differs")
    return manifest


def floor_4h(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    return value.replace(hour=value.hour - value.hour % 4, minute=0, second=0, microsecond=0)


def collect_due(root: Path, anchor: datetime = DEFAULT_ANCHOR, *, max_intervals: int = 42,
                clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), **kwargs) -> tuple[Path, ...]:
    now = clock()
    anchor = anchor.astimezone(timezone.utc)
    if int(anchor.timestamp()) % STEP_SECONDS or not 1 <= max_intervals <= 42:
        raise ValueError("Anchor must be 4h-aligned and max_intervals must be 1..42")
    next_start = anchor
    if root.exists():
        for candidate in sorted(root.glob("pf_xbtusd_*/bundle.json")):
            manifest = load_bundle(candidate.parent)
            next_start = max(next_start, datetime.fromisoformat(manifest["end"]))
    cutoff = floor_4h(now)
    created = []
    while next_start + STEP <= cutoff and len(created) < max_intervals:
        created.append(collect_interval(root, next_start, next_start + STEP,
                                        clock=lambda: now, **kwargs))
        next_start += STEP
    return tuple(created)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp needs an offset")
    return parsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect immutable PF_XBTUSD forward evidence")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--anchor", type=_timestamp, default=DEFAULT_ANCHOR)
    parser.add_argument("--max-intervals", type=int, default=42)
    args = parser.parse_args(argv)
    try:
        created = collect_due(args.root, args.anchor, max_intervals=args.max_intervals)
        print(json.dumps({"created": [path.name for path in created], "count": len(created)}, indent=2))
        return 0
    except (OSError, ValueError, MarketDataError) as exc:
        print(f"Forward collection failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
