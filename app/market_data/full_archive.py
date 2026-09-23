"""Bounded selective reads of Kraken's concatenated official history ZIP parts."""

import argparse
import io
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.error import URLError
from urllib.request import Request, build_opener

from app.errors import MarketDataError
from app.market_data.archive import MAX_CSV, MAX_TRANSFER, RangeReader, _NoRedirect
from app.market_data.cli import timestamp
from app.market_data.datasets import save_dataset
from app.market_data.kraken_csv import parse_kraken_csv
from app.market_data.models import TIMEFRAMES

PARTS = tuple(f"https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_Full_2026Q2.zip.part{i:02}"
              for i in range(5))
DOCUMENTATION = "https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data"


def request_part(url, method, headers, limit):
    if url not in PARTS:
        raise MarketDataError("Unapproved full-history source")
    request = Request(url, method=method, headers={"Accept-Encoding": "identity",
                      "User-Agent": "TradingBotResearch/0.1", **headers})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            if method == "GET" and response.status != 206:
                raise MarketDataError("Server ignored byte range; full download refused")
            raw = response.read(limit + 1) if method == "GET" else b""
            if len(raw) > limit:
                raise MarketDataError("Archive download budget exceeded")
            return response.status, {k.lower(): v for k, v in response.headers.items()}, raw
    except (URLError, OSError):
        raise MarketDataError("Official full-history request failed") from None


class MultipartReader(io.RawIOBase):
    """Present concatenated parts as one ZIP, including reads across boundaries."""

    def __init__(self, transport=request_part):
        self.parts = []
        for url in PARTS:
            self.parts.append(RangeReader(url, transport))
        self.size = sum(part.size for part in self.parts)
        self.position = 0

    @property
    def transferred(self):
        return sum(part.transferred for part in self.parts)

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        if whence not in (0, 1, 2):
            raise ValueError("Invalid seek origin")
        destination = offset + (0 if whence == 0 else self.position if whence == 1 else self.size)
        if destination < 0:
            raise ValueError("Negative archive offset")
        self.position = destination
        return destination

    def read(self, size=-1):
        available = max(0, self.size - self.position)
        size = available if size < 0 else min(size, available)
        if self.transferred + size > MAX_TRANSFER:
            raise MarketDataError("Combined archive reads exceed the 20 MB budget")
        remaining, offset, chunks = size, 0, []
        for part in self.parts:
            if remaining and offset <= self.position < offset + part.size:
                local = self.position - offset
                length = min(remaining, part.size - local)
                part.seek(local)
                chunks.append(part.read(length))
                self.position += length
                remaining -= length
            offset += part.size
        return b"".join(chunks)

    def close(self):
        for part in self.parts:
            part.close()
        super().close()


def fetch_full_csv(timeframe: str, transport=request_part) -> tuple[bytes, dict]:
    if timeframe not in ("1h", "4h"):
        raise ValueError("Full-history selective import supports only 1h and 4h")
    expected = f"XBTEUR_{TIMEFRAMES[timeframe] // 60}.csv"
    with MultipartReader(transport) as reader:
        try:
            with zipfile.ZipFile(reader) as archive:
                matches = [e for e in archive.infolist() if PurePosixPath(e.filename).name == expected]
                if len(matches) != 1:
                    raise MarketDataError("Expected exactly one BTC/EUR member")
                entry = matches[0]
                if entry.file_size > MAX_CSV or entry.compress_size > MAX_TRANSFER or entry.flag_bits & 1:
                    raise MarketDataError("Unsupported or oversized archive member")
                raw = archive.read(entry)
        except (zipfile.BadZipFile, NotImplementedError, EOFError) as exc:
            raise MarketDataError("Invalid full-history ZIP or member CRC") from exc
        return raw, {"provider": "Kraken", "format": "official-multipart-ohlcvt-zip-member",
                     "documentation": DOCUMENTATION, "archive_member": entry.filename,
                     "member_crc32": f"{entry.CRC:08x}", "archive_bytes": reader.size,
                     "transferred_bytes": reader.transferred,
                     "parts": [{"url": p.url, "bytes": p.size, "etag": p.etag} for p in reader.parts],
                     "verification": "HTTPS, exact byte ranges, stable per-part ETags and ZIP member CRC; full-archive SHA256 not verified because unused bytes are not downloaded."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Selectively download official BTC/EUR history")
    parser.add_argument("--timeframe", choices=("1h", "4h"), default="4h")
    parser.add_argument("--start", type=timestamp, required=True)
    parser.add_argument("--end", type=timestamp, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.start >= args.end or args.end > datetime(2026, 7, 1, tzinfo=timezone.utc):
            raise ValueError("Use a new output and a valid historical interval ending by 2026-07-01")
        raw, source = fetch_full_csv(args.timeframe)
        candles = parse_kraken_csv(raw, "BTC/EUR", args.timeframe, args.start, args.end)
        report = save_dataset(args.output, candles, symbol="BTC/EUR", timeframe=args.timeframe,
                              start=args.start, end=args.end, raw=raw, source=source,
                              captured_at=datetime.now(timezone.utc))
        print(f"Saved {len(candles)} candles; ready={report.ready}; missing={report.missing_intervals}; transferred={source['transferred_bytes']} bytes")
        return 0 if report.ready else 2
    except (MarketDataError, ValueError, OSError) as exc:
        print(f"History import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
