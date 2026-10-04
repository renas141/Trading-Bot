"""Verified public PF_XBTUSD contract and market-status snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.derivatives.models import PerpetualContract
from app.errors import MarketDataError


INSTRUMENTS_URL = "https://futures.kraken.com/derivatives/api/v3/instruments"
STATUS_URL = "https://futures.kraken.com/derivatives/api/v3/instruments/status"
ALLOWED_URLS = {INSTRUMENTS_URL, STATUS_URL}
MAX_RESPONSE_BYTES = 4_000_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str) -> bytes:
    if url not in ALLOWED_URLS:
        raise MarketDataError("Only fixed public Kraken instrument endpoints are allowed")
    request = Request(url, headers={"User-Agent": "TradingBotResearch/0.1"}, method="GET")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Kraken instrument response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Kraken instrument request failed (HTTP {status})") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Kraken instrument endpoint unavailable") from None


def _decimal(value, name: str, *, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")
    try:
        parsed = Decimal(str(value))
    except Exception:
        raise ValueError(f"Invalid {name}") from None
    if not parsed.is_finite() or parsed < 0 or (parsed == 0 and not allow_zero):
        raise ValueError(f"Invalid {name}")
    return parsed


@dataclass(frozen=True)
class MarginTier:
    threshold: Decimal
    initial_margin: Decimal
    maintenance_margin: Decimal


@dataclass(frozen=True)
class PublicInstrumentSnapshot:
    tick_size: Decimal
    quantity_step: Decimal
    contract_size: Decimal
    maximum_position_size: Decimal
    minimum_trade_size: Decimal | None
    margin_schedule: str
    margin_tiers: tuple[MarginTier, ...]
    tradeable: bool
    expired: bool
    price_dislocated: bool
    extreme_volatility: bool
    volatility_margin_multiplier: Decimal
    server_time: str

    @property
    def venue_maximum_leverage(self) -> int:
        return int(Decimal("1") / self.margin_tiers[0].initial_margin)

    def summary(self, contract: PerpetualContract | None = None) -> dict:
        contract = contract or PerpetualContract()
        checks = {
            "tradeable": self.tradeable,
            "not_expired": not self.expired,
            "price_not_dislocated": not self.price_dislocated,
            "no_extreme_volatility": not self.extreme_volatility,
            "tick_size_matches": contract.tick_size == self.tick_size,
            "quantity_step_matches": contract.quantity_step == self.quantity_step,
            "local_leverage_cap_within_venue": min(10, contract.maximum_leverage)
            <= self.venue_maximum_leverage,
            "local_initial_margin_is_conservative": contract.initial_margin_rate
            >= self.margin_tiers[0].initial_margin,
            "local_maintenance_margin_is_conservative": contract.maintenance_margin_rate
            >= self.margin_tiers[0].maintenance_margin,
        }
        return {
            "schema_version": 1,
            "market": "PF_XBTUSD",
            "server_time": self.server_time,
            "public_contract": {
                "tick_size": str(self.tick_size),
                "quantity_step_from_precision": str(self.quantity_step),
                "contract_size": str(self.contract_size),
                "maximum_position_size": str(self.maximum_position_size),
                "minimum_trade_size": (str(self.minimum_trade_size)
                                       if self.minimum_trade_size is not None else None),
                "eea_margin_schedule": self.margin_schedule,
                "first_initial_margin": str(self.margin_tiers[0].initial_margin),
                "first_maintenance_margin": str(self.margin_tiers[0].maintenance_margin),
                "maximum_leverage_from_first_tier": self.venue_maximum_leverage,
                "tradeable": self.tradeable,
                "expired": self.expired,
                "price_dislocated": self.price_dislocated,
                "extreme_volatility": self.extreme_volatility,
                "volatility_margin_multiplier": str(self.volatility_margin_multiplier),
            },
            "local_model": {
                "tick_size": str(contract.tick_size),
                "quantity_step": str(contract.quantity_step),
                "initial_margin": str(contract.initial_margin_rate),
                "maintenance_margin": str(contract.maintenance_margin_rate),
                "hard_leverage_cap": min(10, contract.maximum_leverage),
            },
            "checks": checks,
            "ready_for_research": all(checks.values()),
            "account_eligibility_verified": False,
            "live_enabled": False,
        }


def _payload(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Invalid Kraken instrument response")
    try:
        value = json.loads(raw, parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Malformed Kraken instrument response") from None
    if not isinstance(value, dict) or value.get("result") != "success":
        raise ValueError("Kraken instrument response was not successful")
    return value


def _margin_tiers(instrument: dict) -> tuple[str, tuple[MarginTier, ...]]:
    schedules = instrument.get("marginSchedules")
    selected = None
    name = None
    if isinstance(schedules, dict):
        for candidate in ("europa", "europa_crypto"):
            block = schedules.get(candidate)
            if isinstance(block, dict) and isinstance(block.get("retail"), list):
                name, selected = f"{candidate}.retail", block["retail"]
                break
    if selected is None:
        raise ValueError("PF_XBTUSD has no explicit EEA retail margin schedule")
    tiers = []
    for row in selected:
        if not isinstance(row, dict):
            raise ValueError("Invalid PF_XBTUSD margin tier")
        threshold = _decimal(row.get("numNonContractUnits"), "margin threshold", allow_zero=True)
        initial = _decimal(row.get("initialMargin"), "initial margin")
        maintenance = _decimal(row.get("maintenanceMargin"), "maintenance margin")
        if initial > 1 or maintenance >= initial:
            raise ValueError("Invalid PF_XBTUSD margin rates")
        tiers.append(MarginTier(threshold, initial, maintenance))
    if (not tiers or tiers[0].threshold != 0
            or any(second.threshold <= first.threshold for first, second in zip(tiers, tiers[1:]))):
        raise ValueError("PF_XBTUSD margin thresholds are not increasing")
    return name, tuple(tiers)


def parse_snapshot(instruments_raw: bytes, status_raw: bytes) -> PublicInstrumentSnapshot:
    instruments_payload, status_payload = _payload(instruments_raw), _payload(status_raw)
    instruments = instruments_payload.get("instruments")
    statuses = status_payload.get("instrumentStatus")
    if not isinstance(instruments, list) or not isinstance(statuses, list):
        raise ValueError("Kraken instrument arrays are missing")
    matches = [item for item in instruments
               if isinstance(item, dict) and item.get("symbol") == "PF_XBTUSD"]
    status_matches = [item for item in statuses
                      if isinstance(item, dict) and item.get("tradeable") == "PF_XBTUSD"]
    if len(matches) != 1 or len(status_matches) != 1:
        raise ValueError("Expected exactly one PF_XBTUSD instrument and status")
    instrument, status = matches[0], status_matches[0]
    if (instrument.get("type") != "flexible_futures"
            or instrument.get("base") not in {"BTC", "XBT"}
            or instrument.get("quote") != "USD"
            or instrument.get("pair") not in {"BTC:USD", "XBT:USD"}
            or type(instrument.get("tradeable")) is not bool
            or type(instrument.get("isExpired")) is not bool):
        raise ValueError("PF_XBTUSD identity or lifecycle fields differ")
    precision = instrument.get("contractValueTradePrecision")
    if type(precision) is not int or not 0 <= precision <= 12:
        raise ValueError("Invalid PF_XBTUSD quantity precision")
    schedule, tiers = _margin_tiers(instrument)
    minimum = instrument.get("minimumTradeSize")
    server_time = instruments_payload.get("serverTime")
    if not isinstance(server_time, str) or not server_time:
        raise ValueError("Kraken instrument server time is missing")
    for name in ("experiencingDislocation", "experiencingExtremeVolatility"):
        if type(status.get(name)) is not bool:
            raise ValueError("Invalid PF_XBTUSD status flags")
    return PublicInstrumentSnapshot(
        tick_size=_decimal(instrument.get("tickSize"), "tick size"),
        quantity_step=Decimal("1").scaleb(-precision),
        contract_size=_decimal(instrument.get("contractSize"), "contract size"),
        maximum_position_size=_decimal(instrument.get("maxPositionSize"), "maximum position"),
        minimum_trade_size=(_decimal(minimum, "minimum trade size") if minimum is not None else None),
        margin_schedule=schedule,
        margin_tiers=tiers,
        tradeable=instrument["tradeable"],
        expired=instrument["isExpired"],
        price_dislocated=status["experiencingDislocation"],
        extreme_volatility=status["experiencingExtremeVolatility"],
        volatility_margin_multiplier=_decimal(
            status.get("extremeVolatilityInitialMarginMultiplier", 1),
            "volatility margin multiplier",
        ),
        server_time=server_time,
    )


def collect_snapshot(target: Path, transport: Callable[[str], bytes] = public_get) -> dict:
    if target.exists():
        raise ValueError("Use a new instrument snapshot directory")
    instruments_raw = transport(INSTRUMENTS_URL)
    status_raw = transport(STATUS_URL)
    snapshot = parse_snapshot(instruments_raw, status_raw)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as directory:
        partial = Path(directory) / "snapshot"
        partial.mkdir()
        (partial / "instruments.raw").write_bytes(instruments_raw)
        (partial / "status.raw").write_bytes(status_raw)
        summary = snapshot.summary()
        summary["collected_at"] = datetime.now(timezone.utc).isoformat()
        (partial / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        hashes = {name: hashlib.sha256((partial / name).read_bytes()).hexdigest()
                  for name in ("instruments.raw", "status.raw", "summary.json")}
        (partial / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "market": "PF_XBTUSD", "sha256": hashes,
            "sources": [INSTRUMENTS_URL, STATUS_URL], "live_enabled": False,
        }, indent=2) + "\n", encoding="utf-8")
        partial.rename(target)
    try:
        load_snapshot(target)
    except BaseException:
        shutil.rmtree(target)
        raise
    return summary


def load_snapshot(target: Path) -> dict:
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != 1 or manifest.get("market") != "PF_XBTUSD"
            or manifest.get("live_enabled") is not False):
        raise ValueError("Instrument snapshot manifest differs")
    expected = manifest.get("sha256")
    if not isinstance(expected, dict) or set(expected) != {
            "instruments.raw", "status.raw", "summary.json"}:
        raise ValueError("Instrument snapshot inventory differs")
    actual = {path.name for path in target.iterdir() if path.is_file()}
    if actual != set(expected) | {"manifest.json"}:
        raise ValueError("Instrument snapshot inventory differs")
    for name, digest in expected.items():
        if hashlib.sha256((target / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Instrument snapshot checksum mismatch: {name}")
    snapshot = parse_snapshot(
        (target / "instruments.raw").read_bytes(), (target / "status.raw").read_bytes()
    )
    summary = json.loads((target / "summary.json").read_text(encoding="utf-8"))
    comparable = dict(summary)
    comparable.pop("collected_at", None)
    if comparable != snapshot.summary():
        raise ValueError("Instrument snapshot summary differs from raw responses")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Capture current public PF_XBTUSD rules")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(collect_snapshot(args.output), indent=2))
        return 0
    except (OSError, ValueError, MarketDataError) as exc:
        print(f"Kraken instrument snapshot failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
