import unittest

import os
import sys

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

from utils import normalize_attribute_payload, normalize_category_pairs, parse_subcategory_values


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
        self.assertEqual(normalized["Weight"], [10])
        self.assertEqual(normalized["Empty"], [])
        self.assertEqual(normalized["NoneValue"], [])

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


if __name__ == "__main__":
    unittest.main()
