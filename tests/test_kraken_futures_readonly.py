import base64
import json
import tempfile
import unittest
from pathlib import Path

from app.errors import ConfigurationError, MarketDataError
from app.exchange.kraken_futures_readonly import (
    KrakenFuturesReadonlyClient,
    configuration_status,
    sign_request,
    write_verified_summary,
)


SECRET = base64.b64encode(b"test-secret").decode()


class KrakenFuturesReadonlyTests(unittest.TestCase):
    def test_signature_matches_fixed_vector(self):
        signature = sign_request(
            SECRET, "/derivatives/api/v3/accounts", "1700000000000"
        )
        self.assertEqual(
            signature,
            "LxGoYdW+I8/k4Mik1LqZ35SLo63OT7cLNgrJHZKoE8qmKWMU9y0gQ38dtOM9mSdEjHyCryVvBQAriVTGwy87qA==",
        )

    def test_snapshot_uses_only_allowlisted_gets_and_hides_credentials(self):
        calls = []

        def transport(url, headers):
            calls.append((url, headers))
            if url.endswith("/check"):
                value = {"permissions": {"general": "READ_ONLY", "transfer": "NO_ACCESS"}}
            elif url.endswith("/accounts"):
                value = {"result": "success", "accounts": {"flex": {"type": "test"}}}
            elif url.endswith("/openpositions"):
                value = {"result": "success", "openPositions": []}
            elif url.endswith("/fills"):
                value = {"result": "success", "fills": [{"symbol": "PF_XBTUSD"}]}
            else:
                value = {"result": "success", "instruments": [{
                    "symbol": "PF_XBTUSD", "minimumTradeSize": 0.0001,
                    "restricted": False, "isExpired": False,
                }]}
            return json.dumps(value).encode()

        client = KrakenFuturesReadonlyClient(
            "public-key", SECRET, transport=transport, nonce=lambda: 1700000000000
        )
        snapshot = client.account_snapshot()
        self.assertEqual(snapshot.summary()["account_count"], 1)
        self.assertEqual(snapshot.summary()["fill_count"], 1)
        self.assertTrue(snapshot.summary()["pf_xbtusd"]["accessible"])
        self.assertTrue(snapshot.summary()["pf_xbtusd"]["eligible"])
        self.assertEqual(snapshot.summary()["pf_xbtusd"]["minimum_trade_size"], "0.0001")
        self.assertFalse(snapshot.summary()["order_capability"])
        self.assertEqual(len(calls), 5)
        for url, headers in calls:
            self.assertTrue(url.startswith("https://futures.kraken.com/"))
            self.assertEqual(headers["APIKey"], "public-key")
            self.assertNotIn(SECRET, json.dumps(snapshot.summary()))

    def test_rejects_overprivileged_key_before_account_reads(self):
        calls = []

        def transport(url, headers):
            calls.append(url)
            return json.dumps({
                "permissions": {"general": "FULL_ACCESS", "transfer": "NO_ACCESS"}
            }).encode()

        client = KrakenFuturesReadonlyClient("key", SECRET, transport=transport)
        with self.assertRaisesRegex(ConfigurationError, "READ_ONLY"):
            client.account_snapshot()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("/check"))

    def test_malformed_account_response_is_rejected(self):
        responses = iter([
            {"permissions": {"general": "READ_ONLY", "transfer": "NO_ACCESS"}},
            {"result": "success", "accounts": []},
            {"result": "success", "openPositions": []},
            {"result": "success", "fills": []},
            {"result": "success", "instruments": []},
        ])
        client = KrakenFuturesReadonlyClient(
            "key", SECRET,
            transport=lambda url, headers: json.dumps(next(responses)).encode(),
        )
        with self.assertRaisesRegex(MarketDataError, "unexpected shape"):
            client.account_snapshot()

    def test_unconfigured_status_contains_no_secret_values(self):
        status = configuration_status({})
        self.assertFalse(status["configured"])
        self.assertFalse(status["order_capability"])
        self.assertFalse(status["credentials_persisted"])

    def test_unknown_endpoint_cannot_be_signed(self):
        with self.assertRaises(ConfigurationError):
            sign_request(SECRET, "/derivatives/api/v3/sendorder", "1")

    def test_only_redacted_readonly_summary_can_be_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            summary = {
                "mode": "read_only",
                "permissions": {"general": "READ_ONLY", "transfer": "NO_ACCESS"},
                "pf_xbtusd": {"accessible": True, "eligible": True},
                "order_capability": False, "transfer_capability": False,
                "api_secret": "must-never-be-written",
            }
            write_verified_summary(path, summary)
            stored = json.loads(path.read_text())
            self.assertEqual(stored["schema_version"], 1)
            self.assertIn("verified_at", stored)
            self.assertNotIn("secret", json.dumps(stored).lower())
            with self.assertRaises(ConfigurationError):
                write_verified_summary(path, {**summary, "order_capability": True})


if __name__ == "__main__":
    unittest.main()
