import unittest
from unittest.mock import patch

try:
    import run._2_content_generation as content_generation
    _HAS_DEPS = True
except ModuleNotFoundError:
    _HAS_DEPS = False


class HttpFetchTests(unittest.TestCase):
    @unittest.skipUnless(_HAS_DEPS, "requests is not available in test env")
    def test_insecure_host_disables_ssl_verify(self):
        content_generation.config["fetch_insecure_hosts"] = "www.omdceventos.com,example.com"
        with patch("run._2_content_generation.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            mock_get.return_value.text = ""
            mock_get.return_value.headers = {}
            content_generation._fetch_with_retries("https://www.omdceventos.com/evento/test")
            kwargs = mock_get.call_args.kwargs
            self.assertIn("verify", kwargs)
            self.assertFalse(kwargs["verify"])


if __name__ == "__main__":
    unittest.main()
