import os
import sys
import unittest
from unittest.mock import Mock, patch
import types

RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")
    requests_stub.get = Mock()
    sys.modules["requests"] = requests_stub

from recovery_wp_ids import (
    RecoveryRunner,
    WordPressRecoveryClient,
    build_variation_key,
    extract_product_id_from_url,
    get_acf_value,
    group_events,
    match_variations,
    normalize_date,
    normalize_distance,
    normalize_time,
    normalize_type,
    normalize_url,
    write_report,
)


class RecoveryNormalizationTests(unittest.TestCase):
    def test_extract_product_id_from_supported_urls(self):
        self.assertEqual(extract_product_id_from_url("https://site.test/?p=26252"), 26252)
        self.assertEqual(extract_product_id_from_url("https://site.test/?post=26252"), 26252)
        self.assertEqual(extract_product_id_from_url("https://site.test/wp-admin/post.php?post=26252&action=edit"), 26252)

    def test_normalize_url(self):
        self.assertEqual(
            normalize_url("HTTP://www.Example.test/path/?b=2&a=1&utm_source=x"),
            "example.test/path?a=1&b=2",
        )

    def test_normalize_date_time_distance_type(self):
        self.assertEqual(normalize_date("10/05/2026"), "2026-05-10")
        self.assertEqual(normalize_date("10-05-2026-pt"), "2026-05-10")
        self.assertEqual(normalize_time("1000-pt"), "10:00")
        self.assertEqual(normalize_distance("5-km-pt"), "5 km")
        self.assertEqual(normalize_distance("21097-km-pt"), "21.097 km")
        self.assertEqual(normalize_type("caminhada"), "walking")
        self.assertEqual(normalize_type("corrida-de-estrada"), "road-running")

    def test_build_variation_key_from_sheet_row(self):
        key = build_variation_key(
            {
                "TYPE": "Walking",
                "DISTANCE": "5-km-pt",
                "TEAM": "",
                "LICENSE": "",
                "RACE START DATE": "10/05/2026",
                "RACE START TIME": "1000",
            }
        )
        self.assertIn(("type", "walking"), key)
        self.assertIn(("distance", "5 km"), key)
        self.assertIn(("date", "2026-05-10"), key)
        self.assertIn(("time", "10:00"), key)


class RecoveryVariationMatchingTests(unittest.TestCase):
    def test_match_en_and_pt_variations(self):
        rows = [
            (
                10,
                {
                    "TYPE": "Walking",
                    "DISTANCE": "5 km",
                    "RACE START DATE": "10/05/2026",
                    "RACE START TIME": "10:00",
                },
            )
        ]
        variations = [
            {
                "id": 91,
                "attributes": [
                    {"name": "Type", "option": "caminhada"},
                    {"name": "Distance", "option": "5-km-pt"},
                    {"name": "Race Start Date", "option": "10-05-2026-pt"},
                    {"name": "Race Start Time", "option": "1000-pt"},
                ],
            }
        ]
        matches, failures = match_variations(rows, variations)
        self.assertEqual(matches, {10: 91})
        self.assertEqual(failures, {})

    def test_missing_distance_can_match(self):
        rows = [(10, {"TYPE": "Kids Race", "DISTANCE": "", "RACE START DATE": "10/05/2026"})]
        variations = [{"id": 91, "attributes": [{"name": "Type", "option": "kids-race-pt"}, {"name": "Race Start Date", "option": "10-05-2026"}]}]
        matches, failures = match_variations(rows, variations)
        self.assertEqual(matches, {10: 91})
        self.assertEqual(failures, {})

    def test_ambiguous_variation_is_not_matched(self):
        rows = [(10, {"TYPE": "Walking", "DISTANCE": "5 km"})]
        variations = [
            {"id": 91, "attributes": [{"name": "Type", "option": "Walking"}, {"name": "Distance", "option": "5 km"}]},
            {"id": 92, "attributes": [{"name": "Type", "option": "Walking"}, {"name": "Distance", "option": "5 km"}]},
        ]
        matches, failures = match_variations(rows, variations)
        self.assertEqual(matches, {})
        self.assertEqual(failures, {10: "ambiguous_variation_match"})


class RecoveryIntegrationLikeTests(unittest.TestCase):
    def test_recover_product_and_variation_ids_from_link_and_hreflang(self):
        wp = Mock()
        wp.get_product.side_effect = lambda product_id: {
            100: {"id": 100, "type": "variable", "permalink": "https://site.test/race-en"},
            200: {"id": 200, "type": "variable", "permalink": "https://site.test/pt/race"},
        }[product_id]
        wp.validate_product.return_value = True
        wp.get_html.side_effect = [
            '<link rel="alternate" hreflang="pt-pt" href="https://site.test/pt/race">',
            '<link rel="shortlink" href="https://site.test/?p=200">',
        ]
        wp.find_hreflang_url.return_value = "https://site.test/pt/race"
        wp.extract_product_id_from_html.return_value = 200
        wp.get_variations.side_effect = [
            [{"id": 11, "attributes": [{"name": "Type", "option": "Walking"}, {"name": "Distance", "option": "5 km"}]}],
            [{"id": 22, "attributes": [{"name": "Type", "option": "caminhada"}, {"name": "Distance", "option": "5-km-pt"}]}],
        ]

        result = RecoveryRunner(wp).recover_row(
            2,
            {"LINK RACEFINDER": "https://site.test/wp-admin/post.php?post=100", "RACE NAME": "Race"},
            [(3, {"TYPE": "Walking", "DISTANCE": "5 km"})],
        )

        self.assertEqual(result.updates["WP PRODUCT ID EN"], 100)
        self.assertEqual(result.updates["WP PRODUCT ID PT"], 200)
        self.assertEqual(result.updates["WP VARIATION ID EN:3"], 11)
        self.assertEqual(result.updates["WP VARIATION ID PT:3"], 22)

    def test_group_events_and_existing_ids_are_not_overwritten_by_apply_filter(self):
        rows = [
            (2, {"STATUS": "Published", "WP PRODUCT ID EN": "100"}),
            (3, {"TYPE": "Walking", "WP VARIATION ID EN": "11"}),
            (4, {"STATUS": "Revised (complete)", "WP PRODUCT ID EN": ""}),
        ]
        groups = group_events(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0][2][0][0], 3)

    def test_client_extracts_product_id_from_html(self):
        client = WordPressRecoveryClient("https://site.test", "ck", "cs")
        self.assertEqual(client.extract_product_id_from_html('<link rel="shortlink" href="https://site.test/?p=123">'), 123)
        self.assertEqual(client.extract_product_id_from_html('<a href="https://site.test/wp-json/wp/v2/product/456">json</a>'), 456)

    def test_get_acf_value_supports_acf_and_meta_data(self):
        self.assertEqual(get_acf_value({"acf": {"event_ticket_url": "https://race.test"}}, "event_ticket_url"), "https://race.test")
        self.assertEqual(
            get_acf_value({"meta_data": [{"key": "event_date_start", "value": "20260510"}]}, "event_date_start"),
            "20260510",
        )

    def test_fallback_finds_unique_product_by_website_acf(self):
        wp = Mock()
        wp.search_products.return_value = []
        wp.iter_products.return_value = [
            {"id": 100, "type": "variable", "name": "Other", "acf": {"event_ticket_url": "https://other.test"}},
            {
                "id": 200,
                "type": "variable",
                "name": "Porto Half Marathon",
                "acf": {"event_ticket_url": "https://race.test", "event_date_start": "20260510"},
            },
        ]
        real_client = WordPressRecoveryClient("https://site.test", "ck", "cs")
        wp.validate_product.side_effect = real_client.validate_product
        wp.product_match_score.side_effect = real_client.product_match_score

        product_id, source, reason = RecoveryRunner(wp).find_product_by_fallbacks(
            {"WEBSITE": "https://race.test/", "EVENT START DATE": "10/05/2026", "RACE NAME": "Porto Half Marathon"},
            preferred_lang="EN",
        )

        self.assertEqual(product_id, 200)
        self.assertEqual(source, "website_acf")
        self.assertEqual(reason, "")

    def test_fallback_rejects_ambiguous_composite_match(self):
        wp = Mock()
        products = [
            {
                "id": 200,
                "type": "variable",
                "name": "Porto Half Marathon",
                "acf": {"event_date_start": "20260510", "event_location_text": "Porto"},
                "categories": [{"name": "Running"}],
            },
            {
                "id": 201,
                "type": "variable",
                "name": "Porto Half Marathon",
                "acf": {"event_date_start": "20260510", "event_location_text": "Porto"},
                "categories": [{"name": "Running"}],
            },
        ]
        wp.search_products.return_value = products
        wp.iter_products.return_value = []
        real_client = WordPressRecoveryClient("https://site.test", "ck", "cs")
        wp.validate_product.side_effect = real_client.validate_product
        wp.product_match_score.side_effect = real_client.product_match_score

        product_id, _source, reason = RecoveryRunner(wp).find_product_by_fallbacks(
            {
                "EVENT START DATE": "10/05/2026",
                "LOCATION (CITY)": "Porto",
                "CATEGORY": "Running",
                "RACE NAME": "Porto Half Marathon",
            },
            preferred_lang="EN",
        )

        self.assertIsNone(product_id)
        self.assertEqual(reason, "ambiguous_product_match")

    def test_store_api_variations_are_normalized(self):
        client = WordPressRecoveryClient("https://site.test", "ck", "cs")
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "variations": [
                {
                    "id": 77,
                    "attributes": [
                        {"name": "Type", "value": "Walking"},
                        {"name": "Distance", "value": "5 km"},
                    ],
                }
            ]
        }
        with patch("requests.get", return_value=response):
            variations = client.get_store_api_variations(100)
        self.assertEqual(variations, [{"id": 77, "attributes": [{"name": "Type", "option": "Walking"}, {"name": "Distance", "option": "5 km"}]}])

    def test_get_variations_falls_back_when_store_api_has_no_attributes(self):
        client = WordPressRecoveryClient("https://site.test", "ck", "cs")
        store_response = Mock()
        store_response.status_code = 200
        store_response.json.return_value = {"variations": [{"id": 77, "attributes": []}]}
        rest_response = Mock()
        rest_response.raise_for_status.return_value = None
        rest_response.json.return_value = [{"id": 88, "attributes": [{"name": "Type", "option": "Walking"}]}]

        with patch("requests.get", side_effect=[store_response, rest_response]):
            variations = client.get_variations(100)

        self.assertEqual(variations, [{"id": 88, "attributes": [{"name": "Type", "option": "Walking"}]}])

    def test_write_report_creates_csv(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".csv") as report:
            result = RecoveryRunner(Mock()).recover_row
            self.assertTrue(callable(result))
            from recovery_wp_ids import RecoveryResult

            write_report(report.name, [RecoveryResult(row_index=2, race_name="Race", updates={"WP PRODUCT ID EN": 100})], "dry-run")
            with open(report.name, encoding="utf-8") as report_file:
                content = report_file.read()
        self.assertIn("row_index", content)
        self.assertIn("Race", content)


if __name__ == "__main__":
    unittest.main()
