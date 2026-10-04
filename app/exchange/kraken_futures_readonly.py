"""Strictly read-only Kraken Derivatives account inspection.

This module intentionally exposes no order, transfer, or settings mutation.
Credentials are accepted in memory and are never persisted.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.errors import ConfigurationError, MarketDataError


BASE_URL = "https://futures.kraken.com"
MAX_RESPONSE_BYTES = 2_000_000
READ_ONLY_ENDPOINTS = {
    "permissions": "/api/auth/v1/api-keys/v3/check",
    "accounts": "/derivatives/api/v3/accounts",
    "open_positions": "/derivatives/api/v3/openpositions",
    "fills": "/derivatives/api/v3/fills",
    "trading_instruments": "/derivatives/api/v3/trading/instruments",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sign_request(secret: str, endpoint_path: str, nonce: str,
                 encoded_query: str = "") -> str:
    """Build Kraken's Authent header from the encoded URI component."""
    if endpoint_path not in READ_ONLY_ENDPOINTS.values():
        raise ConfigurationError("Endpoint is not on the read-only allowlist")
    if not nonce.isdecimal() or not secret:
        raise ConfigurationError("Invalid Kraken signing inputs")
    try:
        key = base64.b64decode(secret, validate=True)
    except (binascii.Error, ValueError):
        raise ConfigurationError("Kraken API secret is not valid base64") from None
    digest = hashlib.sha256(
        (encoded_query + nonce + endpoint_path).encode("utf-8")
    ).digest()
    return base64.b64encode(hmac.new(key, digest, hashlib.sha512).digest()).decode("ascii")


def readonly_get(url: str, headers: dict[str, str]) -> bytes:
    """Perform one bounded GET to an explicitly allowlisted private endpoint."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "futures.kraken.com"
            or parsed.fragment or parsed.path not in READ_ONLY_ENDPOINTS.values()):
        raise MarketDataError("Only allowlisted Kraken read-only endpoints are permitted")
    if not {"APIKey", "Authent", "Nonce"} <= set(headers):
        raise MarketDataError("Kraken authentication headers are incomplete")
    request = Request(url, headers=headers, method="GET")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Kraken private response exceeds size limit")
        return raw
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise MarketDataError(f"Kraken read-only request failed (HTTP {status})") from None
    except (URLError, TimeoutError, OSError):
        raise MarketDataError("Kraken read-only endpoint unavailable") from None


@dataclass(frozen=True)
class ReadonlyAccountSnapshot:
    general_permission: str
    transfer_permission: str
    accounts: dict = field(repr=False)
    open_positions: tuple[dict, ...] = field(repr=False)
    fills: tuple[dict, ...] = field(repr=False)
    trading_instruments: tuple[dict, ...] = field(repr=False)

    def summary(self) -> dict:
        matches = [item for item in self.trading_instruments
                   if item.get("symbol") == "PF_XBTUSD"]
        instrument = matches[0] if len(matches) == 1 else None
        return {
            "mode": "read_only",
            "permissions": {
                "general": self.general_permission,
                "transfer": self.transfer_permission,
            },
            "account_count": len(self.accounts),
            "open_position_count": len(self.open_positions),
            "fill_count": len(self.fills),
            "accessible_instrument_count": len(self.trading_instruments),
            "pf_xbtusd": {
                "accessible": instrument is not None,
                "eligible": (
                    instrument is not None
                    and instrument.get("restricted") is False
                    and instrument.get("isExpired") is False
                ),
                "minimum_trade_size": (
                    str(instrument.get("minimumTradeSize"))
                    if instrument is not None and instrument.get("minimumTradeSize") is not None
                    else None
                ),
                "restricted": instrument.get("restricted") if instrument is not None else None,
                "expired": instrument.get("isExpired") if instrument is not None else None,
            },
            "order_capability": False,
            "transfer_capability": False,
        }


Transport = Callable[[str, dict[str, str]], bytes]


class KrakenFuturesReadonlyClient:
    """Read account state only, after enforcing least-privilege key permissions."""

    def __init__(self, api_key: str, api_secret: str, *, transport: Transport = readonly_get,
                 nonce: Callable[[], int] = lambda: time.time_ns() // 1_000_000) -> None:
        if not api_key or not api_secret:
            raise ConfigurationError("Kraken read-only credentials are missing")
        self._api_key = api_key
        self._api_secret = api_secret
        self._transport = transport
        self._nonce = nonce

    def _get(self, name: str, params: dict[str, str] | None = None) -> dict:
        try:
            path = READ_ONLY_ENDPOINTS[name]
        except KeyError:
            raise ConfigurationError("Endpoint is not on the read-only allowlist") from None
        encoded_query = urlencode(params or {})
        nonce = str(self._nonce())
        signature = sign_request(self._api_secret, path, nonce, encoded_query)
        url = BASE_URL + path + (("?" + encoded_query) if encoded_query else "")
        raw = self._transport(url, {
            "Accept": "application/json",
            "User-Agent": "TradingBotResearch/0.1-readonly",
            "APIKey": self._api_key,
            "Authent": signature,
            "Nonce": nonce,
        })
        if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
            raise MarketDataError("Invalid Kraken read-only response")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MarketDataError("Malformed Kraken read-only response") from None
        if not isinstance(payload, dict):
            raise MarketDataError("Malformed Kraken read-only response")
        if payload.get("result") == "error" or payload.get("error"):
            raise MarketDataError("Kraken rejected the read-only request")
        return payload

    def verify_permissions(self) -> tuple[str, str]:
        payload = self._get("permissions")
        permissions = payload.get("permissions")
        if not isinstance(permissions, dict):
            raise MarketDataError("Kraken did not return API-key permissions")
        general = permissions.get("general")
        transfer = permissions.get("transfer")
        if general != "READ_ONLY" or transfer != "NO_ACCESS":
            raise ConfigurationError(
                "API key must have general READ_ONLY and transfer NO_ACCESS permissions"
            )
        return general, transfer

    def account_snapshot(self) -> ReadonlyAccountSnapshot:
        general, transfer = self.verify_permissions()
        accounts_payload = self._get("accounts")
        positions_payload = self._get("open_positions")
        fills_payload = self._get("fills")
        instruments_payload = self._get("trading_instruments")
        accounts = accounts_payload.get("accounts")
        positions = positions_payload.get("openPositions")
        fills = fills_payload.get("fills")
        instruments = instruments_payload.get("instruments")
        if (accounts_payload.get("result") != "success" or not isinstance(accounts, dict)
                or positions_payload.get("result") != "success" or not isinstance(positions, list)
                or fills_payload.get("result") != "success" or not isinstance(fills, list)
                or instruments_payload.get("result") != "success"
                or not isinstance(instruments, list)
                or not all(isinstance(item, dict) for item in positions + fills + instruments)):
            raise MarketDataError("Kraken account response has an unexpected shape")
        return ReadonlyAccountSnapshot(
            general, transfer, accounts, tuple(positions), tuple(fills), tuple(instruments)
        )


def configuration_status(environ: dict[str, str] | None = None) -> dict:
    values = os.environ if environ is None else environ
    return {
        "mode": "read_only",
        "configured": bool(values.get("KRAKEN_FUTURES_API_KEY")
                           and values.get("KRAKEN_FUTURES_API_SECRET")),
        "required_permissions": {"general": "READ_ONLY", "transfer": "NO_ACCESS"},
        "allowed_reads": sorted(READ_ONLY_ENDPOINTS),
        "order_capability": False,
        "transfer_capability": False,
        "credentials_persisted": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Kraken Derivatives in read-only mode")
    parser.add_argument("command", choices=("status", "verify"))
    args = parser.parse_args(argv)
    status = configuration_status()
    if args.command == "status":
        print(json.dumps(status, indent=2))
        return 0
    if not status["configured"]:
        print("Read-only Kraken credentials are not configured", file=sys.stderr)
        return 2
    try:
        client = KrakenFuturesReadonlyClient(
            os.environ["KRAKEN_FUTURES_API_KEY"],
            os.environ["KRAKEN_FUTURES_API_SECRET"],
        )
        print(json.dumps(client.account_snapshot().summary(), indent=2))
        return 0
    except (ConfigurationError, MarketDataError) as exc:
        print(f"Kraken read-only verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
