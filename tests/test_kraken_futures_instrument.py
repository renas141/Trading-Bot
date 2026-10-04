import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.errors import MarketDataError
from app.exchange.kraken_futures_instrument import (
    INSTRUMENTS_URL,
    STATUS_URL,
    collect_snapshot,
    load_snapshot,
    parse_snapshot,
    public_get,
)


def instruments_payload():
    return json.dumps({
        "result": "success", "serverTime": "2026-10-04T00:00:00Z",
        "instruments": [{
            "symbol": "PF_XBTUSD", "pair": "BTC:USD", "base": "BTC", "quote": "USD",
            "type": "flexible_futures", "tickSize": 1, "contractSize": 1,
            "contractValueTradePrecision": 4, "maxPositionSize": 1200,
            "minimumTradeSize": 0.0001, "tradeable": True, "isExpired": False,
            "marginSchedules": {"europa": {"retail": [
                {"numNonContractUnits": 0, "initialMargin": 0.1, "maintenanceMargin": 0.05},
                {"numNonContractUnits": 30000000, "initialMargin": 0.2,
                 "maintenanceMargin": 0.1},
            ]}},
        }],
    }).encode()


def status_payload(dislocated=False):
    return json.dumps({
        "result": "success", "serverTime": "2026-10-04T00:00:01Z",
        "instrumentStatus": [{
            "tradeable": "PF_XBTUSD", "experiencingDislocation": dislocated,
            "experiencingExtremeVolatility": False,
            "extremeVolatilityInitialMarginMultiplier": 1,
        }],
    }).encode()


class KrakenFuturesInstrumentTests(unittest.TestCase):
    def test_parses_eea_rules_and_matches_conservative_local_model(self):
        value = parse_snapshot(instruments_payload(), status_payload())
        self.assertEqual(value.tick_size, Decimal("1"))
        self.assertEqual(value.quantity_step, Decimal("0.0001"))
        self.assertEqual(value.venue_maximum_leverage, 10)
        self.assertTrue(value.summary()["ready_for_research"])
        self.assertFalse(value.summary()["live_enabled"])

    def test_market_dislocation_fails_readiness(self):
        value = parse_snapshot(instruments_payload(), status_payload(True))
        self.assertFalse(value.summary()["ready_for_research"])
        self.assertFalse(value.summary()["checks"]["price_not_dislocated"])

    def test_missing_eea_schedule_is_rejected(self):
        payload = json.loads(instruments_payload())
        del payload["instruments"][0]["marginSchedules"]
        with self.assertRaisesRegex(ValueError, "EEA"):
            parse_snapshot(json.dumps(payload).encode(), status_payload())

    def test_unapproved_url_is_rejected_before_network(self):
        with self.assertRaises(MarketDataError):
            public_get("https://example.com/derivatives/api/v3/instruments")

    def test_saved_snapshot_is_recomputed_and_checksum_verified(self):
        def transport(url):
            return instruments_payload() if url == INSTRUMENTS_URL else status_payload()

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "snapshot"
            summary = collect_snapshot(target, transport)
            self.assertEqual(load_snapshot(target), summary)
            (target / "status.raw").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_snapshot(target)

    def test_existing_target_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "snapshot"
            target.mkdir()
            marker = target / "keep"
            marker.write_text("unchanged")
            with self.assertRaisesRegex(ValueError, "new"):
                collect_snapshot(target, lambda url: b"unused")
            self.assertEqual(marker.read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main()
