import os
import sys
import unittest

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

from rf_schedule import parse_datetime, parse_price, parse_price_changes


class ParseDatetimeTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(parse_datetime(""), (None, None))
        self.assertEqual(parse_datetime(None), (None, None))

    def test_date_only_defaults_to_18(self):
        self.assertEqual(parse_datetime("2026-07-28"), ("2026-07-28 18:00", None))
        self.assertEqual(parse_datetime("28/07/2026"), ("2026-07-28 18:00", None))

    def test_custom_default_time(self):
        self.assertEqual(parse_datetime("2026-07-28", default_time="23:59"),
                         ("2026-07-28 23:59", None))

    def test_with_time_preserved(self):
        self.assertEqual(parse_datetime("2026-07-28 17:30"), ("2026-07-28 17:30", None))
        self.assertEqual(parse_datetime("2026-07-28 17:30:00"), ("2026-07-28 17:30", None))
        self.assertEqual(parse_datetime("28/07/2026 09:05"), ("2026-07-28 09:05", None))
        self.assertEqual(parse_datetime("2026-07-28T17:30"), ("2026-07-28 17:30", None))

    def test_invalid(self):
        norm, err = parse_datetime("not a date")
        self.assertIsNone(norm)
        self.assertIsNotNone(err)
        # сообщение об ошибке — на английском (клиент читает EN)
        self.assertIn("unrecognized date/time", err)


class ParsePriceTests(unittest.TestCase):
    def test_plain_and_comma(self):
        self.assertEqual(parse_price("15"), "15.00")
        self.assertEqual(parse_price("15,50"), "15.50")
        self.assertEqual(parse_price("€ 20.00"), "20.00")

    def test_invalid(self):
        self.assertIsNone(parse_price(""))
        self.assertIsNone(parse_price("abc"))
        self.assertIsNone(parse_price("1.2.3"))


class ParsePriceChangesTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(parse_price_changes(""), ([], []))
        self.assertEqual(parse_price_changes(None), ([], []))

    def test_single(self):
        result, errors = parse_price_changes("2026-07-20 18:00 = 15")
        self.assertEqual(errors, [])
        self.assertEqual(result, [{"datetime": "2026-07-20 18:00", "price": "15.00"}])

    def test_multiple_semicolon(self):
        result, errors = parse_price_changes(
            "2026-07-20 18:00 = 15; 2026-07-25 18:00 = 20; 2026-07-30=25"
        )
        self.assertEqual(errors, [])
        self.assertEqual(result, [
            {"datetime": "2026-07-20 18:00", "price": "15.00"},
            {"datetime": "2026-07-25 18:00", "price": "20.00"},
            {"datetime": "2026-07-30 00:00", "price": "25.00"},
        ])

    def test_date_only_defaults_to_midnight(self):
        result, errors = parse_price_changes("2026-08-01 = 20")
        self.assertEqual(errors, [])
        self.assertEqual(result, [{"datetime": "2026-08-01 00:00", "price": "20.00"}])

    def test_multiple_newline(self):
        result, errors = parse_price_changes("2026-07-20 18:00 = 15\n2026-07-25 = 20")
        self.assertEqual(errors, [])
        self.assertEqual(len(result), 2)

    def test_partial_errors_are_flagged(self):
        result, errors = parse_price_changes("2026-07-20 18:00 = 15; garbage; 2026-07-25=abc")
        # только валидная запись попадает в результат
        self.assertEqual(result, [{"datetime": "2026-07-20 18:00", "price": "15.00"}])
        self.assertEqual(len(errors), 2)
        # ошибки — на английском
        self.assertTrue(all(any(w in e for w in ("missing", "invalid", "unrecognized")) for e in errors))


if __name__ == "__main__":
    unittest.main()
