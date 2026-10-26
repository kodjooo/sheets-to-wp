import os
import sys
import types
import unittest
from unittest.mock import patch


RUN_DIR = os.path.join(os.path.dirname(__file__), "..", "run")
if RUN_DIR not in sys.path:
    sys.path.insert(0, RUN_DIR)

# Local stub to avoid dependency on external package in tests.
if "woocommerce" not in sys.modules:
    woocommerce_stub = types.ModuleType("woocommerce")

    class _APIStub:
        def __init__(self, *args, **kwargs):
            pass

    woocommerce_stub.API = _APIStub
    sys.modules["woocommerce"] = woocommerce_stub

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.files = types.SimpleNamespace(create=lambda **kwargs: types.SimpleNamespace(id="file_1"))
    openai_stub.OpenAI = lambda *args, **kwargs: types.SimpleNamespace(
        responses=types.SimpleNamespace(create=lambda **_kw: types.SimpleNamespace(output_text="{}"))
    )
    sys.modules["openai"] = openai_stub

if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")
    requests_stub.get = lambda *args, **kwargs: None
    sys.modules["requests"] = requests_stub

if "pytz" not in sys.modules:
    pytz_stub = types.ModuleType("pytz")
    pytz_stub.timezone = lambda _name: None
    sys.modules["pytz"] = pytz_stub

if "_1_google_loader" not in sys.modules:
    gl_stub = types.ModuleType("_1_google_loader")
    gl_stub.load_config = lambda: {}
    gl_stub.load_revised_rows = lambda: []
    gl_stub.load_all_rows = lambda: ([], {})
    gl_stub.update_status_to_published = lambda *args, **kwargs: None
    gl_stub.batch_update_cells = lambda *args, **kwargs: None
    sys.modules["_1_google_loader"] = gl_stub

if "_2_content_generation" not in sys.modules:
    cg_stub = types.ModuleType("_2_content_generation")
    cg_stub.extract_text_from_url = lambda *args, **kwargs: ("", None)
    cg_stub.build_first_assistant_prompt = lambda *args, **kwargs: ""
    cg_stub.validate_source_texts = lambda *args, **kwargs: []
    cg_stub.normalize_regulations_link_block = lambda payload, _url: payload
    cg_stub.call_openai_assistant = lambda *args, **kwargs: None
    cg_stub.call_second_openai_assistant = lambda *args, **kwargs: None
    cg_stub.generate_image = lambda *args, **kwargs: {"url": "", "id": None}
    cg_stub.get_coordinates_with_city_fallback = lambda *args, **kwargs: ("", "")
    cg_stub.translate_title_to_en = lambda text: text
    sys.modules["_2_content_generation"] = cg_stub

if "_3_create_product" not in sys.modules:
    cp_stub = types.ModuleType("_3_create_product")
    cp_stub.create_or_update_product = lambda *args, **kwargs: 0
    cp_stub.get_category_id_by_name = lambda *args, **kwargs: 0
    cp_stub.get_category_translation_id = lambda *args, **kwargs: 0
    cp_stub.ensure_category_translation = lambda *args, **kwargs: 0
    sys.modules["_3_create_product"] = cp_stub

if "_4_create_translation" not in sys.modules:
    ct_stub = types.ModuleType("_4_create_translation")
    ct_stub.create_or_update_product_pt = lambda *args, **kwargs: 0
    sys.modules["_4_create_translation"] = ct_stub

if "_5_taxonomy_and_attributes" not in sys.modules:
    ta_stub = types.ModuleType("_5_taxonomy_and_attributes")
    ta_stub.assign_attributes_to_product = lambda *args, **kwargs: None
    sys.modules["_5_taxonomy_and_attributes"] = ta_stub

if "_6_create_variations" not in sys.modules:
    v_stub = types.ModuleType("_6_create_variations")
    v_stub.sync_variations_by_ids = lambda *args, **kwargs: {}
    v_stub.reapply_price_schedules = lambda *args, **kwargs: None
    sys.modules["_6_create_variations"] = v_stub

if "utils" not in sys.modules:
    utils_stub = types.ModuleType("utils")
    utils_stub.normalize_attribute_payload = lambda payload: payload or {}
    utils_stub.parse_subcategory_values = lambda value: [v.strip() for v in str(value).split(",") if v.strip()]
    utils_stub.get_missing_pt_fields = lambda _result: []
    utils_stub.normalize_category_pairs = lambda pairs: [
        (c, (s or None)) for c, s in pairs if c
    ]
    utils_stub.normalize_attribute_name = lambda name: name
    sys.modules["utils"] = utils_stub

if "website_snapshot" not in sys.modules:
    ws_stub = types.ModuleType("website_snapshot")
    ws_stub.compute_website_hash = lambda *_args, **_kwargs: ("", "")
    ws_stub.has_website_changed = lambda *_args, **_kwargs: (False, "")
    ws_stub.send_telegram_notification = lambda *_args, **_kwargs: True
    sys.modules["website_snapshot"] = ws_stub

import main  # noqa: E402


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class RevisedIncompleteGenerationTests(unittest.TestCase):
    @patch.object(main, "create_product_pt_primary", return_value=202)
    @patch.object(main, "sync_variations_by_ids", return_value={})
    @patch.object(main, "assign_attributes_to_product")
    @patch.object(main, "create_product_pt", return_value=202)
    @patch.object(main, "create_product_en", return_value=101)
    @patch.object(main, "compute_website_hash", return_value=("snapshot-hash", "normalized"))
    @patch.object(main, "translate_title_to_en", return_value="Race Name EN")
    @patch.object(main, "extract_text_from_url", return_value=("source text", None))
    @patch.object(main, "build_first_assistant_prompt", return_value="combined source text")
    @patch.object(main, "validate_source_texts", return_value=[])
    @patch.object(main, "generate_image", return_value={"url": "https://example.test/image.png", "id": None})
    @patch.object(main, "call_openai_assistant", return_value={"facts": "ok"})
    @patch.object(
        main,
        "call_second_openai_assistant",
        return_value={
            "summary": "Summary EN",
            "org_info": "Org EN",
            "benefits": ["Benefit 1", "Benefit 2"],
            "faq": "Q: Q1 / A: A1",
            "summary_pt": "Summary PT",
            "org_info_pt": "Org PT",
            "benefits_pt": ["Beneficio 1", "Beneficio 2"],
            "faq_pt": "Q: Q1 / A: A1",
            "image_prompt": "image prompt",
        },
    )
    @patch.object(main, "get_missing_pt_fields", return_value=[])
    @patch.object(main, "get_coordinates_with_city_fallback", return_value=(1.0, 2.0))
    @patch.object(main, "load_config", return_value={"wp_url": "https://example.test", "consumer_key": "ck", "consumer_secret": "cs"})
    @patch.object(main, "log_network_diagnostics")
    @patch.object(main.requests, "get", return_value=_FakeResponse({"slug": "race-slug", "permalink": "https://example.test/event/race-slug"}))
    def test_revised_incomplete_generates_ai_fields(
        self,
        _mock_requests_get,
        _mock_log_network,
        _mock_load_config,
        _mock_geo,
        _mock_missing,
        _mock_second,
        _mock_first,
        _mock_gen_image,
        _mock_validate,
        _mock_build_prompt,
        _mock_extract,
        _mock_translate,
        _mock_hash,
        _mock_create_en,
        _mock_create_pt,
        _mock_assign_attrs,
        _mock_sync_vars,
        _mock_create_pt_primary,
    ):
        row = {
            "ID": "1",
            "STATUS": "Revised (incomplete)",
            "RACE NAME (PT)": "Corrida Teste",
            "WEBSITE": "https://example.com",
            "REGULATIONS": "",
            "CATEGORY": "Road",
            "SUBCATEGORY": "",
            "ATTRIBUTE": "",
            "VALUE": "",
            "PRICE": "10",
            "LOCATION": "Lisbon",
            "LOCATION (CITY)": "Lisbon",
            "WP PRODUCT ID EN": "",
            "WP PRODUCT ID PT": "",
            "WP VARIATION ID EN": "",
            "WP VARIATION ID PT": "",
        }
        headers = {
            "SUMMARY": 1,
            "ORG INFO": 2,
            "BENEFITS": 3,
            "FAQ": 4,
            "SUMMARY (PT)": 5,
            "ORG INFO (PT)": 6,
            "BENEFITS (PT)": 7,
            "FAQ (PT)": 8,
            "STATUS": 9,
            "IMAGE ID": 10,
        }
        updates = []

        def _capture_update(row_index, values, _headers):
            updates.append((row_index, values.copy()))

        category_root_map = '{"road": {"en_parent_id": 10, "pt_parent_id": 11}}'
        with patch.dict("os.environ", {"CATEGORY_ROOT_MAP_JSON": category_root_map}):
            with patch.object(main, "load_all_rows", return_value=([(2, row)], headers)):
                with patch.object(main, "batch_update_cells", side_effect=_capture_update):
                    with patch.object(main, "SKIP_AI", False):
                        with patch.object(main, "SKIP_IMAGE", True):
                            main.run_automation()

        ai_update = next((values for _idx, values in updates if "SUMMARY" in values and "FAQ (PT)" in values), None)
        self.assertIsNotNone(ai_update, "Expected AI fields update for Revised (incomplete)")
        self.assertEqual(ai_update.get("SUMMARY"), "Summary EN")
        self.assertEqual(ai_update.get("SUMMARY (PT)"), "Summary PT")
        self.assertEqual(ai_update.get("FAQ (PT)"), "Q: Q1 / A: A1")
        # Cancellation policy: без данных подставляется фолбэк, дописанный в конец ORG INFO
        self.assertTrue(ai_update.get("ORG INFO", "").startswith("Org EN"))
        self.assertIn(main.CANCELLATION_FALLBACK_EN, ai_update.get("ORG INFO", ""))
        self.assertIn(main.CANCELLATION_FALLBACK_PT, ai_update.get("ORG INFO (PT)", ""))
        # Организатор: колонки пишутся (пустые, т.к. AI их не вернул)
        self.assertIn("ORGANIZER NAME", ai_update)
        self.assertIn("ORGANIZER EMAIL", ai_update)

        status_update = next((values for _idx, values in updates if "STATUS" in values), None)
        self.assertIsNotNone(status_update)
        self.assertEqual(status_update.get("STATUS"), main.STATUS_PUBLISHED_INCOMPLETE)

    @patch.object(main, "create_product_pt_primary", return_value=202)
    @patch.object(main, "sync_variations_by_ids", return_value={})
    @patch.object(main, "assign_attributes_to_product")
    @patch.object(main, "create_product_pt", return_value=101)
    @patch.object(main, "create_product_en", return_value=101)
    @patch.object(main, "compute_website_hash", return_value=("snapshot-hash", "normalized"))
    @patch.object(main, "translate_title_to_en", return_value="Race Name EN")
    @patch.object(main, "extract_text_from_url", return_value=("source text", None))
    @patch.object(main, "build_first_assistant_prompt", return_value="combined source text")
    @patch.object(main, "validate_source_texts", return_value=[])
    @patch.object(main, "generate_image", return_value={"url": "", "id": None})
    @patch.object(main, "call_openai_assistant", return_value={"facts": "ok"})
    @patch.object(main, "call_second_openai_assistant", return_value={"summary": "s"})
    @patch.object(main, "get_missing_pt_fields", return_value=[])
    @patch.object(main, "get_coordinates_with_city_fallback", return_value=(1.0, 2.0))
    @patch.object(main, "load_config", return_value={"wp_url": "https://example.test", "consumer_key": "ck", "consumer_secret": "cs"})
    @patch.object(main, "log_network_diagnostics")
    @patch.object(main.requests, "get", return_value=_FakeResponse({"slug": "race-slug", "permalink": "https://example.test/event/race-slug"}))
    def test_subcategories_collected_from_variation_rows(self, *_mocks):
        """Подкатегории со строк-вариаций собираются как есть — каждый дочерний
        элемент под СВОИМ родителем. Одна гонка может быть в разных родительских
        категориях (пример 2451: главная Cycling/MTB + вариация Running/Walking)."""
        main_row = {
            "ID": "1", "STATUS": "Revised (complete)", "RACE NAME (PT)": "Corrida Teste",
            "WEBSITE": "https://example.com", "REGULATIONS": "",
            "CATEGORY": "Cycling", "SUBCATEGORY": "MTB",
            "ATTRIBUTE": "", "VALUE": "", "PRICE": "10",
            "LOCATION": "Lisbon", "LOCATION (CITY)": "Lisbon",
            "WP PRODUCT ID EN": "", "WP PRODUCT ID PT": "",
            "WP VARIATION ID EN": "", "WP VARIATION ID PT": "",
        }
        # строка-вариация ДРУГОЙ родительской категории — легитимна, должна попасть
        var_walking = dict(main_row, ID="", STATUS="", CATEGORY="Running", SUBCATEGORY="Walking", DISTANCE="10 km")
        # ещё одна подкатегория того же (главного) родителя
        var_gravel = dict(main_row, ID="", STATUS="", CATEGORY="Cycling", SUBCATEGORY="Gravel", DISTANCE="80 km")
        headers = {"STATUS": 9}
        rows = [(2, main_row), (3, var_walking), (4, var_gravel)]

        captured = {}

        def _spy(row):
            captured["extra"] = set(row.get("extra_categories") or [])
            return []

        with patch.dict("os.environ", {"CATEGORY_ROOT_MAP_JSON": "{}"}):
            with patch.object(main, "load_all_rows", return_value=(rows, headers)):
                with patch.object(main, "batch_update_cells"):
                    with patch.object(main, "_build_pt_category_ids_from_en", side_effect=_spy):
                        with patch.object(main, "SKIP_AI", True):
                            with patch.object(main, "SKIP_IMAGE", True):
                                main.run_automation()

        extra = captured.get("extra", set())
        # каждый дочерний элемент под своим родителем
        self.assertIn(("Cycling", "MTB"), extra)
        self.assertIn(("Running", "Walking"), extra)
        self.assertIn(("Cycling", "Gravel"), extra)
        # Walking НЕ должен оказаться под Cycling (родитель — из своей строки)
        self.assertNotIn(("Cycling", "Walking"), extra)


class SpanishPipelineTests(unittest.TestCase):
    def run_spanish(self, enabled="true", country="all"):
        from contextlib import ExitStack
        row = {"ID": "ES-1", "COUNTRY": "Spain", "STATUS": "Revised (incomplete)",
               "RACE NAME (ES)": "Carrera", "RACE NAME (PT)": "Do not use",
               "WP PRODUCT ID ES": "901", "WP PRODUCT ID PT": "101",
               "WP PRODUCT ID EN": "902", "WP VARIATION ID ES": "903",
               "WP VARIATION ID EN": "904", "LOCATION (CITY)": "Badalona, Barcelona",
               "WEBSITE": "https://event.example.test", "CATEGORY": "Running"}
        required = ["SUMMARY (ES)", "ORG INFO (ES)", "BENEFITS (ES)", "FAQ (ES)"]
        headers = {key: i for i, key in enumerate(list(row) + required, 1)}
        updates = []
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                "ENABLE_SPAIN": enabled, "SPAIN_WP_HOST": "dev.example.test",
                "PROCESS_COUNTRY": country, "MAX_EVENTS_PER_RUN": "0", "MAX_WEBSITE_CHECKS_PER_RUN": "0",
                "CATEGORY_ROOT_MAP_JSON": '{"Running":{"en_parent_id":1,"es_parent_id":2}}'}))
            mocks = {}
            values = {"load_config": {"wp_url": "https://dev.example.test", "consumer_key": "x", "consumer_secret": "y"},
                      "load_all_rows": ([(2, row)], headers), "log_network_diagnostics": None,
                      "get_coordinates_with_city_fallback": (41.0, 2.0), "translate_title_to_en": "Race",
                      "extract_text_from_url": ("source", None), "build_first_assistant_prompt": "source",
                      "validate_source_texts": [], "_build_pt_category_ids_from_en": [],
                      "create_product_pt_primary": 901, "create_product_pt": 902,
                      "assign_attributes_to_product": None, "sync_variations_by_ids": {2: 903},
                      "reapply_price_schedules": None, "compute_website_hash": ("hash", "")}
            for name, value in values.items():
                mocks[name] = stack.enter_context(patch.object(main, name, return_value=value))
            stack.enter_context(patch.object(main, "_batch_update_cells", side_effect=lambda n, u, h: updates.append(dict(u))))
            stack.enter_context(patch.object(main.requests, "get", return_value=_FakeResponse({"permalink": "https://dev.example.test/event/race"})))
            stack.enter_context(patch.object(main, "SKIP_AI", True))
            stack.enter_context(patch.object(main, "SKIP_IMAGE", True))
            main.run_automation()
        return updates, mocks

    def test_es_columns_and_existing_ids_are_preserved(self):
        from country_profile import active_profile, PT
        updates, mocks = self.run_spanish()
        self.assertTrue(any("SUMMARY (ES)" in update for update in updates))
        self.assertFalse(any("SUMMARY (PT)" in update or "WP PRODUCT ID PT" in update for update in updates))
        final = next(update for update in updates if "WP PRODUCT ID ES" in update)
        self.assertEqual(final["WP PRODUCT ID ES"], 901)
        self.assertEqual(mocks["create_product_pt_primary"].call_args.kwargs["existing_product_id"], "901")
        self.assertTrue(all(call.kwargs.get("lang") in ("es", "en")
                            for call in mocks["sync_variations_by_ids"].call_args_list))
        self.assertEqual(active_profile(), PT)

    def test_pt_run_does_not_process_es_row(self):
        updates, mocks = self.run_spanish(country="pt")
        self.assertEqual(updates, [])
        mocks["create_product_pt_primary"].assert_not_called()
        mocks["get_coordinates_with_city_fallback"].assert_not_called()


    def test_disabled_es_has_no_sheet_or_product_writes(self):
        from country_profile import active_profile, PT
        updates, mocks = self.run_spanish("false")
        self.assertEqual(updates, [])
        mocks["create_product_pt_primary"].assert_not_called()
        mocks["translate_title_to_en"].assert_not_called()
        self.assertEqual(active_profile(), PT)


class CountryWebsiteMonitorTests(unittest.TestCase):
    def test_es_checks_only_its_country_with_its_budget(self):
        from contextlib import ExitStack
        rows = [(i, {"ID": str(i), "COUNTRY": country, "STATUS": "Published (incomplete)",
                     "WEBSITE": url, "WEBSITE SNAPSHOT HASH": "old"})
                for i, country, url in [(2, "Portugal", "https://pt.example"),
                                         (3, "Spain", "https://es-one.example"),
                                         (4, "Spain", "https://es-two.example")]]
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"PROCESS_COUNTRY": "es", "MAX_WEBSITE_CHECKS_PER_RUN": "1"}))
            stack.enter_context(patch.object(main, "load_all_rows", return_value=(rows, {})))
            stack.enter_context(patch.object(main, "load_config", return_value={}))
            stack.enter_context(patch.object(main, "log_network_diagnostics"))
            stack.enter_context(patch.object(main, "TELEGRAM_NOTIFICATIONS_ENABLED", False))
            writes = stack.enter_context(patch.object(main, "_batch_update_cells"))
            check = stack.enter_context(patch.object(main, "has_website_changed", return_value=(False, "old")))
            main.run_automation()
            check.assert_called_once_with("old", "https://es-one.example")
            self.assertEqual(writes.call_args.args[0], 3)


if __name__ == "__main__":
    unittest.main()
