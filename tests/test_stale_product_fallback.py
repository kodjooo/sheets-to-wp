import os
import sys
import unittest
from unittest.mock import patch

import requests

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

import _3_create_product as cp


class _FakeResp:
    def __init__(self, ok, status_code, text=""):
        self.ok = ok
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} error")


class StaleProductFallbackTests(unittest.TestCase):
    @patch.object(cp, "create_product", return_value=999)
    def test_recreates_when_existing_id_is_invalid(self, mock_create):
        put_resp = _FakeResp(False, 400)
        get_resp = _FakeResp(False, 404, '{"code":"woocommerce_rest_product_invalid_id"}')
        with patch.object(cp.requests, "put", return_value=put_resp), \
             patch.object(cp.requests, "get", return_value=get_resp):
            result = cp.create_or_update_product({"RACE NAME (PT)": "Race X"}, existing_product_id=123)
        self.assertEqual(result, 999)
        mock_create.assert_called_once()

    @patch.object(cp, "create_product", return_value=999)
    def test_raises_when_product_exists_but_update_fails(self, mock_create):
        put_resp = _FakeResp(False, 400, "bad request")
        get_resp = _FakeResp(True, 200, "{}")
        with patch.object(cp.requests, "put", return_value=put_resp), \
             patch.object(cp.requests, "get", return_value=get_resp):
            with self.assertRaises(requests.HTTPError):
                cp.create_or_update_product({"RACE NAME (PT)": "Race X"}, existing_product_id=123)
        mock_create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
