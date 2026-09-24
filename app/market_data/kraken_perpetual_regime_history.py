"""Verified 4h PF_XBTUSD regime dataset from paginated public analytics."""

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
from app.market_data.kraken_perpetual_regime import KINDS, _number


ROOT = "https://futures.kraken.com/api/charts/v1/analytics/PF_XBTUSD/"
DOCUMENTATION = "https://docs.kraken.com/api/docs/futures-api/charts/market-analytics"
INTERVAL = 4 * 60 * 60
MAX_RANGE_SECONDS = 370 * 24 * 60 * 60
MAX_RESPONSE_BYTES = 8_000_000
MAX_PAGES = 100
FIELDS = (
    "open_interest", "aggressor_differential", "liquidation_volume",
    "rolling_volatility", "long_short_ratio", "buy_volume", "sell_volume",
    "cumulative_volume_delta",
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str) -> bytes:
    parsed = urlsplit(url)
    prefix = "/api/charts/v1/analytics/PF_XBTUSD/"
    kind = parsed.path.removeprefix(prefix) if parsed.path.startswith(prefix) else ""
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
        since, end, interval = (int(query[name][0]) for name in ("since", "to", "interval"))
    except (KeyError, TypeError, ValueError, IndexError):
        raise MarketDataError("Invalid Kraken regime-history query") from None
    if (parsed.scheme != "https" or parsed.netloc != "futures.kraken.com" or parsed.fragment
            or kind not in KINDS or set(query) != {"since", "to", "interval"}
            or any(len(values) != 1 for values in query.values())
            or interval != INTERVAL or since < 0 or end <= since
            or end - since > MAX_RANGE_SECONDS):
        raise MarketDataError("Only bounded public PF_XBTUSD 4h regime history is allowed")
    try:
        request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Kraken regime-history response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Kraken regime-history request failed (HTTP {status})") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Kraken regime-history endpoint unavailable") from None


def _values(kind: str, data: object, length: int) -> list[dict[str, Decimal]]:
    try:
        if kind == "open-interest":
            if not isinstance(data, list) or len(data) != length:
                raise ValueError("Open-interest length mismatch")
            result = []
            for row in data:
                if not isinstance(row, list) or len(row) != 4:
                    raise ValueError("Open interest must be OHLC")
                result.append({"open_interest": _number(row[3], kind, positive=True)})
            return result
        if kind == "cvd":
            if not isinstance(data, dict) or set(data) != {"buy_volume", "sell_volume", "cvd"}:
                raise ValueError("CVD keys differ")
            if any(not isinstance(data[key], list) or len(data[key]) != length for key in data):
                raise ValueError("CVD length mismatch")
            return [{
                "buy_volume": _number(data["buy_volume"][index], "buy volume", nonnegative=True),
                "sell_volume": _number(data["sell_volume"][index], "sell volume", nonnegative=True),
                "cumulative_volume_delta": _number(data["cvd"][index], "CVD"),
            } for index in range(length)]
        if not isinstance(data, list) or len(data) != length:
            raise ValueError("Simple series length mismatch")
        field = kind.replace("-", "_")
        nonnegative = kind in ("liquidation-volume", "rolling-volatility", "long-short-ratio")
        return [{field: _number(value, kind, nonnegative=nonnegative)} for value in data]
    except (ValueError, TypeError, ArithmeticError):
        raise MarketDataError(f"Malformed Kraken {kind} history") from None


def parse_page(raw: bytes, kind: str, cursor: int, end: int):
    try:
        payload = json.loads(raw, parse_float=Decimal)
        result = payload["result"]
        timestamps = result["timestamp"]
        more = result["more"]
        if (payload.get("errors") != [] or type(more) is not bool
                or not isinstance(timestamps, list) or not timestamps):
            raise ValueError("Partial or malformed history payload")
        previous = None
        for stamp in timestamps:
            if (type(stamp) is not int or stamp % INTERVAL
                    or not cursor - INTERVAL <= stamp <= end
                    or (previous is not None and stamp <= previous)):
                raise ValueError("Invalid history timestamp")
            previous = stamp
        values = _values(kind, result["data"], len(timestamps))
        rows = {stamp: value for stamp, value in zip(timestamps, values)
                if cursor <= stamp < end}
        if more and (not rows or max(rows) + INTERVAL >= end):
            raise ValueError("Pagination cannot make progress")
        return rows, more
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ArithmeticError):
        raise MarketDataError(f"Malformed Kraken {kind} history page") from None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(output: Path, start: datetime, end: datetime,
             transport: Callable[[str], bytes] = public_get,
             clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if (output.exists() or start >= end or int(start.timestamp()) % INTERVAL
            or int(end.timestamp()) % INTERVAL or (end - start).total_seconds() > MAX_RANGE_SECONDS):
        raise ValueError("Use a new directory and an aligned range of at most 370 days")
    captured = clock()
    if captured.tzinfo is None or end > captured.astimezone(timezone.utc):
        raise ValueError("Regime history end must not be in the future")
    output.mkdir(parents=True)
    try:
        raw_dir = output / "raw"
        raw_dir.mkdir()
        series: dict[str, dict[int, dict[str, Decimal]]] = {}
        source_pages = {}
        start_seconds, end_seconds = int(start.timestamp()), int(end.timestamp())
        for kind in KINDS:
            cursor, combined, pages = start_seconds, {}, []
            for page in range(MAX_PAGES):
                url = ROOT + kind + "?" + urlencode(
                    {"since": cursor, "to": end_seconds, "interval": INTERVAL}
                )
                raw = transport(url)
                if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
                    raise MarketDataError("Invalid or oversized regime-history response")
                target = raw_dir / f"{kind}-{page:03}.json"
                target.write_bytes(raw)
                rows, more = parse_page(raw, kind, cursor, end_seconds)
                for stamp, value in rows.items():
                    if stamp in combined and combined[stamp] != value:
                        raise ValueError(f"Conflicting duplicate {kind} row")
                    combined[stamp] = value
                pages.append({"file": target.relative_to(output).as_posix(), "url": url,
                              "sha256": _sha(target), "rows": len(rows)})
                if not more:
                    break
                cursor = max(rows) + INTERVAL
            else:
                raise ValueError(f"Too many {kind} pages")
            if not combined:
                raise ValueError(f"No {kind} history in requested range")
            series[kind], source_pages[kind] = combined, pages

        first = max(min(rows) for rows in series.values())
        last_exclusive = min(max(rows) + INTERVAL for rows in series.values())
        expected = tuple(range(first, last_exclusive, INTERVAL))
        if not expected:
            raise ValueError("Regime histories do not overlap")
        gaps = {kind: [stamp for stamp in expected if stamp not in rows]
                for kind, rows in series.items()}
        if any(gaps.values()):
            raise ValueError("Regime history has missing aligned intervals")
        csv_path = output / "regime.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("timestamp", *FIELDS))
            writer.writeheader()
            for stamp in expected:
                row = {"timestamp": datetime.fromtimestamp(stamp, timezone.utc).isoformat()}
                for values in series.values():
                    row.update({name: str(value) for name, value in values[stamp].items()})
                if set(row) != {"timestamp", *FIELDS}:
                    raise ValueError("Merged regime row has missing or extra fields")
                writer.writerow(row)
        quality = {
            "ready": True, "rows": len(expected),
            "start": datetime.fromtimestamp(first, timezone.utc).isoformat(),
            "end": datetime.fromtimestamp(last_exclusive, timezone.utc).isoformat(),
            "requested_start": start.isoformat(), "requested_end": end.isoformat(),
            "gaps": {kind: [] for kind in KINDS},
        }
        write_json(output / "quality.json", quality)
        files = sorted(path.relative_to(output).as_posix()
                       for path in output.rglob("*") if path.is_file())
        write_json(output / "manifest.json", {
            "schema_version": 1, "market_type": "linear_perpetual_regime",
            "market_id": "PF_XBTUSD", "symbol": "BTC/USD", "timeframe": "4h",
            "timestamp_semantics": "analytics interval timestamp", "end_semantics": "exclusive",
            "start": quality["start"], "end": quality["end"],
            "requested_start": start.isoformat(), "requested_end": end.isoformat(),
            "captured_at": captured.astimezone(timezone.utc).isoformat(),
            "fields": list(FIELDS),
            "source": {"provider": "Kraken Futures", "documentation": DOCUMENTATION,
                       "analytics_types": list(KINDS), "pages": source_pages},
            "sha256": {name: _sha(output / name) for name in files},
            "ready": True,
            "activation": {"strategy_selected": False, "paper_enabled": False, "live_enabled": False},
        })
        return quality
    except BaseException:
        shutil.rmtree(output)
        raise


def load_dataset(path: Path):
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != 1
            or manifest.get("market_type") != "linear_perpetual_regime"
            or manifest.get("market_id") != "PF_XBTUSD" or manifest.get("ready") is not True
            or manifest.get("fields") != list(FIELDS)):
        raise ValueError("Regime dataset is not ready")
    hashes = manifest.get("sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Regime dataset has no checksums")
    for name, expected in hashes.items():
        candidate = (path / name).resolve()
        if not candidate.is_relative_to(path.resolve()) or not candidate.is_file() or _sha(candidate) != expected:
            raise ValueError(f"Regime dataset checksum mismatch: {name}")
    rows = []
    with (path / "regime.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["timestamp", *FIELDS]:
            raise ValueError("Regime CSV header differs")
        previous = None
        for raw in reader:
            stamp = datetime.fromisoformat(raw["timestamp"])
            if (stamp.tzinfo is None or stamp.utcoffset() != timedelta(0) or stamp.microsecond
                    or int(stamp.timestamp()) % INTERVAL
                    or (previous is not None and stamp != previous + timedelta(seconds=INTERVAL))):
                raise ValueError("Regime CSV time axis is not continuous")
            values = {
                name: _number(
                    raw[name], name,
                    positive=name == "open_interest",
                    nonnegative=name in {
                        "liquidation_volume", "rolling_volatility", "long_short_ratio",
                        "buy_volume", "sell_volume",
                    },
                )
                for name in FIELDS
            }
            rows.append({"timestamp": stamp, **values})
            previous = stamp
    if (not rows or rows[0]["timestamp"].isoformat() != manifest["start"]
            or (rows[-1]["timestamp"].timestamp() + INTERVAL) != datetime.fromisoformat(manifest["end"]).timestamp()):
        raise ValueError("Regime CSV coverage differs from manifest")
    return tuple(rows), manifest


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp needs an offset")
    return parsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Download verified PF_XBTUSD 4h regime history")
    parser.add_argument("--start", type=_timestamp, required=True)
    parser.add_argument("--end", type=_timestamp, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(download(args.output, args.start, args.end), indent=2))
        return 0
    except (OSError, ValueError, MarketDataError) as exc:
        print(f"Regime-history download failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
