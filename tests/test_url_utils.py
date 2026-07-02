import os
import sys
import unittest

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

from url_utils import normalize_http_url, unwrap_google_viewer_url


class NormalizeHttpUrlTests(unittest.TestCase):
    def test_adds_scheme_when_missing(self):
        self.assertEqual(normalize_http_url("example.com/x"), "https://example.com/x")

    def test_keeps_existing_scheme(self):
        self.assertEqual(normalize_http_url("http://example.com"), "http://example.com")

    def test_empty(self):
        self.assertEqual(normalize_http_url(""), "")
        self.assertEqual(normalize_http_url(None), "")


class UnwrapGoogleViewerUrlTests(unittest.TestCase):
    def test_unwraps_viewerng_plain_target(self):
        url = (
            "https://docs.google.com/viewerng/viewer?url="
            "https://stopandgo.net/storage/events/tex/6a2c44e2990ad_Regulamento_TEX_2026.pdf"
        )
        self.assertEqual(
            unwrap_google_viewer_url(url),
            "https://stopandgo.net/storage/events/tex/6a2c44e2990ad_Regulamento_TEX_2026.pdf",
        )

    def test_unwraps_viewer_encoded_target(self):
        url = "https://docs.google.com/viewer?url=https%3A%2F%2Fexample.com%2Ffile.pdf"
        self.assertEqual(unwrap_google_viewer_url(url), "https://example.com/file.pdf")

    def test_leaves_direct_pdf_untouched(self):
        url = "https://stopandgo.net/storage/x.pdf"
        self.assertEqual(unwrap_google_viewer_url(url), url)

    def test_leaves_google_drive_untouched(self):
        url = "https://drive.google.com/file/d/ABC123/view"
        self.assertEqual(unwrap_google_viewer_url(url), url)

    def test_viewer_without_url_param_returns_original(self):
        url = "https://docs.google.com/viewer"
        self.assertEqual(unwrap_google_viewer_url(url), url)

    def test_empty(self):
        self.assertEqual(unwrap_google_viewer_url(""), "")
        self.assertEqual(unwrap_google_viewer_url(None), "")


if __name__ == "__main__":
    unittest.main()
