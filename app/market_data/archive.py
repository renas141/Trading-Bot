"""Read one Kraken CSV from a remote ZIP using bounded HTTP byte ranges."""

import io
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Callable
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.errors import MarketDataError
from app.market_data.models import TIMEFRAMES

ARCHIVES = {quarter: f"https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_{quarter}.zip"
            for quarter in ("2026Q1", "2026Q2")}
MAX_TRANSFER = 20_000_000
MAX_CSV = 100_000_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_range(url: str, method: str, headers: dict[str, str], limit: int) -> tuple[int, dict[str, str], bytes]:
    if url not in ARCHIVES.values():
        raise MarketDataError("Archive URL is not an approved official quarterly source")
    request = Request(url, method=method, headers={"Accept-Encoding": "identity",
                      "User-Agent": "TradingBotResearch/0.1", **headers})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            if method == "GET" and response.status != 206:
                raise MarketDataError("Archive server ignored byte range; full download refused")
            raw = response.read(limit + 1) if method == "GET" else b""
            if len(raw) > limit:
                raise MarketDataError("Archive range exceeds download budget")
            return response.status, {k.lower(): v for k, v in response.headers.items()}, raw
    except (URLError, OSError):
        raise MarketDataError("Official archive request failed; no partial dataset published") from None


class RangeReader(io.RawIOBase):
    """Seekable ZIP source that never silently downloads the entire archive."""

    def __init__(self, url: str, transport: Callable = request_range) -> None:
        self.url, self.transport = url, transport
        status, headers, _ = transport(url, "HEAD", {}, 0)
        try:
            self.size = int(headers["content-length"])
            self.etag = headers["etag"]
            if status != 200 or self.size <= 0 or self.etag.startswith("W/"):
                raise ValueError("Expected a stable byte-addressable archive")
        except (KeyError, ValueError) as exc:
            raise MarketDataError("Archive metadata missing or invalid") from exc
        self.position = self.transferred = 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence not in (0, 1, 2):
            raise ValueError("Invalid seek origin")
        destination = offset + (0 if whence == 0 else self.position if whence == 1 else self.size)
        if destination < 0:
            raise ValueError("Negative archive offset")
        self.position = destination
        return destination

    def read(self, size: int = -1) -> bytes:
        size = max(0, self.size - self.position) if size < 0 else min(size, max(0, self.size - self.position))
        if size == 0:
            return b""
        if self.transferred + size > MAX_TRANSFER:
            raise MarketDataError("Selective archive download exceeded the 20 MB budget")
        start, end = self.position, self.position + size - 1
        status, headers, raw = self.transport(self.url, "GET",
            {"Range": f"bytes={start}-{end}", "If-Match": self.etag}, size)
        expected = f"bytes {start}-{end}/{self.size}"
        if (status != 206 or headers.get("content-range") != expected or len(raw) != size
                or headers.get("etag") != self.etag
                or headers.get("content-encoding", "identity") != "identity"):
            raise MarketDataError("Archive range or ETag changed during download")
        self.position += size
        self.transferred += size
        return raw


def fetch_archive_csv(quarter: str, timeframe: str, transport: Callable = request_range
                      ) -> tuple[bytes, dict[str, object], datetime, datetime]:
    if quarter not in ARCHIVES or timeframe not in TIMEFRAMES:
        raise ValueError("Unsupported archive quarter or timeframe")
    expected = f"XBTEUR_{TIMEFRAMES[timeframe] // 60}.csv"
    with RangeReader(ARCHIVES[quarter], transport) as reader:
        try:
            with zipfile.ZipFile(reader) as archive:
                matches = [entry for entry in archive.infolist() if PurePosixPath(entry.filename).name == expected]
                if len(matches) != 1:
                    raise MarketDataError("Archive must contain exactly one matching BTC/EUR CSV")
                entry = matches[0]
                if entry.file_size > MAX_CSV or entry.compress_size > MAX_TRANSFER or entry.flag_bits & 1:
                    raise MarketDataError("Selected archive entry is too large or encrypted")
                with archive.open(entry) as handle:
                    raw = handle.read(MAX_CSV + 1)
                if len(raw) != entry.file_size or len(raw) > MAX_CSV:
                    raise MarketDataError("Selected CSV length is invalid")
                metadata = {"provider": "Kraken", "format": "official-ohlcvt-zip-member",
                            "url": ARCHIVES[quarter], "etag": reader.etag,
                            "archive_member": entry.filename, "member_crc32": f"{entry.CRC:08x}",
                            "archive_bytes": reader.size, "transferred_bytes": reader.transferred,
                            "verification": "HTTPS, stable ETag, ZIP member CRC32; full archive checksum not fetched"}
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
            raise MarketDataError("Invalid or unsupported official ZIP archive") from exc
    year, number = int(quarter[:4]), int(quarter[-1])
    start = datetime(year, (number - 1) * 3 + 1, 1, tzinfo=timezone.utc)
    end = datetime(year + (number == 4), 1 if number == 4 else number * 3 + 1, 1, tzinfo=timezone.utc)
    return raw, metadata, start, end
