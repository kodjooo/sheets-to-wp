import os
import sys
import unittest
from unittest.mock import patch
import types

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

# Локальный stub, чтобы тест не зависел от установленного пакета woocommerce.
if "woocommerce" not in sys.modules:
    woocommerce_stub = types.ModuleType("woocommerce")
    class _APIStub:  # noqa: D401
        def __init__(self, *args, **kwargs):
            pass
    woocommerce_stub.API = _APIStub
    sys.modules["woocommerce"] = woocommerce_stub

sys.modules.pop("_1_google_loader", None)

google_loader_stub = types.ModuleType("_1_google_loader")
def _load_config_stub():
    return {
        "wp_url": "https://example.test",
        "consumer_key": "ck",
        "consumer_secret": "cs",
        "wcapi_timeout_sec": "10",
        "wcapi_max_attempts": "2",
        "wcapi_base_delay_sec": "0.1",
    }
google_loader_stub.load_config = _load_config_stub
sys.modules["_1_google_loader"] = google_loader_stub

sys.modules.pop("_6_create_variations", None)

from _6_create_variations import sync_variations_by_ids


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        return None


class VariationSyncTests(unittest.TestCase):
    @patch("_6_create_variations._wcapi_request_with_retry")
    def test_sync_variations_updates_creates_and_deletes(self, mock_wcapi):
        calls = []

        def side_effect(method, endpoint, payload=None):
            calls.append((method, endpoint, payload))

            if method == "GET" and endpoint == "products/100":
                return _FakeResponse(
                    json_data={"attributes": [{"id": 9, "name": "Distance"}]}
                )
            if method == "GET" and endpoint == "products/100/variations?per_page=100&page=1":
                return _FakeResponse(
                    json_data=[
                        {"id": 11, "regular_price": "10", "attributes": [{"id": 9, "option": "5 km"}]},
                        {"id": 22, "regular_price": "20", "attributes": [{"id": 9, "option": "10 km"}]},
                    ]
                )
            if method == "GET" and endpoint == "products/100/variations?per_page=100&page=2":
                return _FakeResponse(json_data=[])
            if method == "PUT" and endpoint == "products/100/variations/11":
                return _FakeResponse(json_data={"id": 11})
            if method == "POST" and endpoint == "products/100/variations":
                return _FakeResponse(json_data={"id": 33})
            if method == "DELETE" and endpoint == "products/100/variations/22":
                return _FakeResponse(json_data={"id": 22, "deleted": True})
            raise AssertionError(f"Unexpected call: {method} {endpoint} {payload}")

        mock_wcapi.side_effect = side_effect

        mapping = sync_variations_by_ids(
            100,
            [
                {
                    "row_index": 5001,
                    "existing_variation_id": "11",
                    "regular_price": "15",
                    "attributes": [{"name": "Distance", "option": "5 km"}],
                },
                {
                    "row_index": 5002,
                    "existing_variation_id": "",
                    "regular_price": "25",
                    "attributes": [{"name": "Distance", "option": "21 km"}],
                },
            ],
        )

        self.assertEqual(mapping[5001], 11)
        self.assertEqual(mapping[5002], 33)
        self.assertIn(("PUT", "products/100/variations/11", {"regular_price": "15", "attributes": [{"id": 9, "option": "5 km"}]}), calls)
        self.assertIn(("DELETE", "products/100/variations/22", {"force": True}), calls)

    @patch("_6_create_variations._wcapi_request_with_retry")
    def test_sync_variations_ignores_mismatched_existing_id_and_matches_by_payload(self, mock_wcapi):
        class DummyResponse:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200
                self.text = ""

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        calls = []

        def side_effect(method, endpoint, payload=None):
            calls.append((method, endpoint, payload))
            if method == "GET" and endpoint == "products/100":
                return DummyResponse({"attributes": [{"id": 9, "name": "Distance"}]})
            if method == "GET" and endpoint == "products/100/variations?per_page=100&page=1":
                # Вариации уже есть, но в таблице ID перепутаны между строками.
                return DummyResponse(
                    [
                        {"id": 11, "regular_price": "10", "attributes": [{"id": 9, "option": "5 km"}]},
                        {"id": 22, "regular_price": "20", "attributes": [{"id": 9, "option": "10 km"}]},
                    ]
                )
            if method == "GET" and endpoint == "products/100/variations?per_page=100&page=2":
                return DummyResponse([])
            if method == "DELETE":
                return DummyResponse({})
            if method in {"PUT", "POST"}:
                self.fail(f"Unexpected mutation call {method} {endpoint} {payload}")
            raise AssertionError(f"Unexpected call: {method} {endpoint}")

        mock_wcapi.side_effect = side_effect

        mapping = sync_variations_by_ids(
            100,
            [
                {
                    "row_index": 2,
                    "existing_variation_id": "22",  # неверный ID для этой строки
                    "regular_price": "10",
                    "attributes": [{"name": "Distance", "option": "5 km"}],
                },
                {
                    "row_index": 3,
                    "existing_variation_id": "11",  # неверный ID для этой строки
                    "regular_price": "20",
                    "attributes": [{"name": "Distance", "option": "10 km"}],
                },
            ],
        )

        self.assertEqual(mapping, {2: 11, 3: 22})


if __name__ == "__main__":
    unittest.main()
