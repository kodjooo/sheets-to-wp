import os
import unittest
from unittest.mock import patch

import sys

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

sys.modules.pop("website_snapshot", None)

from website_snapshot import (
    fetch_website_html,
    normalize_html_for_hash,
    compute_website_hash,
    has_website_changed,
)


class WebsiteSnapshotTests(unittest.TestCase):
    @patch("website_snapshot._fetch_html_with_retries")
    def test_fetch_website_html_returns_response_text(self, mock_fetch):
        mock_fetch.return_value = "<html>ok</html>"
        html = fetch_website_html("example.com")
        self.assertEqual(html, "<html>ok</html>")

    def test_normalize_html_for_hash_removes_dynamic_parts(self):
        html = (
            "<html><head><script>var ts=123;</script></head>"
            "<body><!-- c --><a href='/?utm_source=x&v=42'>L</a>"
            "<div nonce='abcdef123456'>x</div></body></html>"
        )
        normalized = normalize_html_for_hash(html)
        self.assertNotIn("<script>", normalized)
        self.assertNotIn("utm_source", normalized)
        self.assertNotIn("nonce='abcdef123456'", normalized)

    @patch("website_snapshot.fetch_website_html")
    def test_compute_website_hash_returns_digest(self, mock_fetch_html):
        mock_fetch_html.return_value = "<html><body>Hello</body></html>"
        digest, normalized = compute_website_hash("https://example.com")
        self.assertEqual(len(digest), 64)
        self.assertTrue(normalized)

    @patch("website_snapshot.compute_website_hash")
    def test_has_website_changed_detects_difference(self, mock_compute_hash):
        mock_compute_hash.return_value = ("new-hash", "normalized")
        changed, current_hash = has_website_changed("old-hash", "https://example.com")
        self.assertTrue(changed)
        self.assertEqual(current_hash, "new-hash")


if __name__ == "__main__":
    unittest.main()
