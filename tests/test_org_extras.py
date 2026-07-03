import os
import sys
import unittest

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

try:
    import main
    _HAS_DEPS = True
except Exception:
    _HAS_DEPS = False


@unittest.skipUnless(_HAS_DEPS, "main import requires deps/env")
class CancellationBlockTests(unittest.TestCase):
    def test_uses_text_when_present(self):
        out = main._append_cancellation_block("Org info", "Refunds until 30 days before.", "en")
        self.assertIn("Refunds until 30 days before.", out)
        self.assertTrue(out.startswith("Org info"))
        self.assertIn("Cancellation", out)

    def test_fallback_en_when_empty(self):
        out = main._append_cancellation_block("Org info", "", "en")
        self.assertIn(main.CANCELLATION_FALLBACK_EN, out)

    def test_fallback_pt_when_empty(self):
        out = main._append_cancellation_block("", "   ", "pt")
        self.assertIn(main.CANCELLATION_FALLBACK_PT, out)

    def test_appended_after_existing_with_separator(self):
        out = main._append_cancellation_block("Existing block", "Policy X", "en")
        self.assertIn("Existing block\n\n<strong>", out)


@unittest.skipUnless(_HAS_DEPS, "main import requires deps/env")
class EmailExtractionTests(unittest.TestCase):
    def test_single(self):
        self.assertEqual(main._extract_valid_emails("geral@stopandgo.pt"), "geral@stopandgo.pt")

    def test_multiple_joined_and_deduped(self):
        raw = "Contacto: a@b.pt, geral@x.com; a@b.pt"
        self.assertEqual(main._extract_valid_emails(raw), "a@b.pt, geral@x.com")

    def test_embedded_in_text(self):
        self.assertEqual(main._extract_valid_emails("Email do organizador: info@evento.pt."), "info@evento.pt")

    def test_junk_returns_empty(self):
        self.assertEqual(main._extract_valid_emails("não disponível"), "")
        self.assertEqual(main._extract_valid_emails(""), "")

    def test_lowercased(self):
        self.assertEqual(main._extract_valid_emails("Geral@StopAndGo.PT"), "geral@stopandgo.pt")


if __name__ == "__main__":
    unittest.main()
