import unittest

import os
import sys

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

from utils import (
    normalize_attribute_payload,
    select_attribute_id,
    normalize_category_pairs,
    parse_subcategory_values,
    get_missing_pt_fields,
    parse_faq_items,
)


class UtilsTests(unittest.TestCase):
    def test_normalize_attribute_payload(self):
        payload = {
            "Color": "Blue",
            "Size": ["M", "L"],
            "Weight": 10,
            "Empty": "",
            "NoneValue": None,
        }
        normalized = normalize_attribute_payload(payload)
        self.assertEqual(normalized["Color"], ["Blue"])
        self.assertEqual(normalized["Size"], ["M", "L"])
        self.assertEqual(normalized["Weight"], ["10"])
        self.assertEqual(normalized["Empty"], [])
        self.assertEqual(normalized["NoneValue"], [])

    def test_normalize_attribute_payload_strips_spaces(self):
        payload = {
            " Running ": " Road Running ",
            "Race Start Date": [" 30/05/2026 ", " "],
            " ": "ignored",
        }
        normalized = normalize_attribute_payload(payload)
        self.assertEqual(normalized["Running"], ["Road Running"])
        self.assertEqual(normalized["Race Start Date"], ["30/05/2026"])
        self.assertNotIn(" ", normalized)

    def test_parse_subcategory_values(self):
        self.assertEqual(parse_subcategory_values("Road, Trail , ,Ultra"), ["Road", "Trail", "Ultra"])
        self.assertEqual(parse_subcategory_values(["Road", " Trail,Ultra "]), ["Road", "Trail", "Ultra"])
        self.assertEqual(parse_subcategory_values(None), [])

    def test_normalize_category_pairs(self):
        raw_pairs = [
            ("Run", "Road, Trail"),
            ("Run", ""),
            ("Cycle", None),
            ("Run", "Trail"),
            ("", "Ignored")
        ]
        normalized = normalize_category_pairs(raw_pairs)
        self.assertEqual(
            normalized,
            [("Run", "Road"), ("Run", "Trail"), ("Run", None), ("Cycle", None)]
        )

    def test_get_missing_pt_fields(self):
        result = {
            "summary": "<p>Text</p>",
            "summary_pt": "",
            "org_info": "Info",
            "org_info_pt": "Info PT",
            "faq": "Q",
            "faq_pt": "",
            "benefits": ["A"],
            "benefits_pt": [],
        }
        missing = get_missing_pt_fields(result)
        self.assertEqual(missing, ["summary_pt", "faq_pt", "benefits_pt"])

        result_ok = {
            "summary": "<p>Text</p>",
            "summary_pt": "<p>Texto</p>",
            "org_info": "",
            "org_info_pt": "",
            "faq": "",
            "faq_pt": "",
            "benefits": [],
            "benefits_pt": [],
        }
        self.assertEqual(get_missing_pt_fields(result_ok), [])

    def test_parse_faq_items(self):
        raw_faq = (
            "<strong>FAQ:</strong>\n"
            "• Q: How do I get there?\n"
            "  A: Use shuttle from city center.\n"
            "• Q: Can kids join?\n"
            "  A: Yes, from 10 years old.\n"
        )
        items = parse_faq_items(raw_faq)
        self.assertEqual(
            items,
            [
                {
                    "item_title": "How do I get there?",
                    "item_description": "Use shuttle from city center.",
                },
                {
                    "item_title": "Can kids join?",
                    "item_description": "Yes, from 10 years old.",
                },
            ],
        )

    def test_select_attribute_id_prefers_slug(self):
        attrs = [
            {"id": 1, "name": "Running", "slug": "running"},
            {"id": 2, "name": "Running", "slug": "running-alt"},
        ]
        self.assertEqual(select_attribute_id(attrs, "Running"), 1)

    def test_select_attribute_id_fallback_name(self):
        attrs = [
            {"id": 5, "name": "Running", "slug": "sport-running"},
        ]
        self.assertEqual(select_attribute_id(attrs, "Running"), 5)

    def test_select_attribute_id_raises_on_ambiguous_name(self):
        attrs = [
            {"id": 7, "name": "Running", "slug": "running-1"},
            {"id": 8, "name": "Running", "slug": "running-2"},
        ]
        with self.assertRaises(RuntimeError):
            select_attribute_id(attrs, "Running")


if __name__ == "__main__":
    unittest.main()
