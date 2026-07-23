import os
import sys
import unittest

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

from rf_location import resolve_municipality


class ResolveMunicipalityTests(unittest.TestCase):
    def test_municipality_first_token(self):
        self.assertEqual(resolve_municipality("Loures, Lisboa"), "Loures")
        self.assertEqual(resolve_municipality("Azambuja, Lisboa"), "Azambuja")

    def test_accents_and_case(self):
        self.assertEqual(resolve_municipality("vila nova de famalicao, Braga"), "Vila Nova de Famalicão")

    def test_no_comma_municipality_equals_name(self):
        self.assertEqual(resolve_municipality("Braga"), "Braga")

    def test_municipality_in_second_token(self):
        # freguesia в первом токене, муниципалитет во втором
        self.assertEqual(resolve_municipality("São Vicente do Paúl, Santarém"), "Santarém")

    def test_international_returns_none(self):
        self.assertIsNone(resolve_municipality("Rio de Janeiro"))
        self.assertIsNone(resolve_municipality("Virtual Race"))

    def test_empty(self):
        self.assertIsNone(resolve_municipality(""))
        self.assertIsNone(resolve_municipality(None))


if __name__ == "__main__":
    unittest.main()
