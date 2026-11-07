import unittest
from unittest.mock import patch, Mock
import os
import sys

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

try:
    import _2_content_generation as content_generation
    _HAS_DEPS = True
except ModuleNotFoundError:
    _HAS_DEPS = False


class HttpFetchTests(unittest.TestCase):
    @unittest.skipUnless(_HAS_DEPS, "requests is not available in test env")
    def test_insecure_host_disables_ssl_verify(self):
        content_generation.config["fetch_insecure_hosts"] = "www.omdceventos.com,example.com"
        with patch("_2_content_generation.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            mock_get.return_value.text = ""
            mock_get.return_value.headers = {}
            content_generation._fetch_with_retries("https://www.omdceventos.com/evento/test")
            kwargs = mock_get.call_args.kwargs
            self.assertIn("verify", kwargs)
            self.assertFalse(kwargs["verify"])


if __name__ == "__main__":
    unittest.main()


def test_forbidden_is_not_retried():
    from requests import Response, HTTPError
    response = Response()
    response.status_code = 403
    error = HTTPError('Forbidden', response=response)
    with patch.dict(content_generation.config, {'fetch_retry_delays_sec': '1,2'}):
        with patch('_2_content_generation.requests.get', side_effect=error) as get:
            with patch('_2_content_generation.time.sleep') as sleep:
                with __import__('pytest').raises(HTTPError):
                    content_generation._fetch_with_retries('https://running.life/test')
                assert get.call_count == 1
                sleep.assert_not_called()


def test_temporary_server_failure_is_retried():
    from requests import Response, HTTPError
    response = Response()
    response.status_code = 503
    success = Mock()
    success.headers = {}
    success.text = '<h1>Race</h1>'
    with patch.dict(content_generation.config, {'fetch_retry_delays_sec': '1'}):
        with patch('_2_content_generation.requests.get', side_effect=[HTTPError(response=response), success]) as get:
            with patch('_2_content_generation.time.sleep'):
                assert content_generation._fetch_with_retries('https://running.life/test') is success
                assert get.call_count == 2
