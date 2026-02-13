import os
import unittest


class TranslationAcfTests(unittest.TestCase):
    def test_pt_translation_uses_acf_endpoint(self):
        file_path = os.path.join(os.path.dirname(__file__), "..", "run", "_4_create_translation.py")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("/wp-json/acf/v3/product/", content)
        self.assertIn("\"event_location_text\": location_city", content)
        self.assertIn("\"event_faq_items\": faq_items_pt", content)


if __name__ == "__main__":
    unittest.main()
