import base64
import json
import unittest

from app.errors import ConfigurationError, MarketDataError
from app.exchange.kraken_futures_readonly import (
    KrakenFuturesReadonlyClient,
    configuration_status,
    sign_request,
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
            else:
                value = {"result": "success", "fills": [{"symbol": "PF_XBTUSD"}]}
            return json.dumps(value).encode()

        client = KrakenFuturesReadonlyClient(
            "public-key", SECRET, transport=transport, nonce=lambda: 1700000000000
        )
        snapshot = client.account_snapshot()
        self.assertEqual(snapshot.summary()["account_count"], 1)
        self.assertEqual(snapshot.summary()["fill_count"], 1)
        self.assertFalse(snapshot.summary()["order_capability"])
        self.assertEqual(len(calls), 4)
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


if __name__ == "__main__":
    unittest.main()
